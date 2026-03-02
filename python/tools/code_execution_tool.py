import asyncio
from dataclasses import dataclass
import shlex
import time
import os
import hashlib
from pathlib import Path
from python.helpers.tool import Tool, Response
from python.helpers import files, rfc_exchange, projects, runtime, settings
from python.helpers.print_style import PrintStyle
from python.helpers.shell_local import LocalInteractiveSession
from python.helpers.shell_ssh import SSHInteractiveSession
from python.helpers.docker import DockerContainerManager
from python.helpers.strings import truncate_text as truncate_text_string
from python.helpers.messages import truncate_text as truncate_text_agent
import re

# Timeouts for python, nodejs, and terminal runtimes.
CODE_EXEC_TIMEOUTS: dict[str, int] = {
    "first_output_timeout": 30,
    "between_output_timeout": 15,
    "max_exec_timeout": 180,
    "dialog_timeout": 5,
}

# Timeouts for output runtime.
OUTPUT_TIMEOUTS: dict[str, int] = {
    "first_output_timeout": 90,
    "between_output_timeout": 45,
    "max_exec_timeout": 300,
    "dialog_timeout": 5,
}

@dataclass
class ShellWrap:
    id: int
    session: LocalInteractiveSession | SSHInteractiveSession
    running: bool

@dataclass
class State:
    ssh_enabled: bool
    shells: dict[int, ShellWrap]


class CodeExecution(Tool):

    # Common shell prompt regex patterns (add more as needed)
    prompt_patterns = [
        re.compile(r"\\(venv\\).+[$#] ?$"),  # (venv) ...$ or (venv) ...#
        re.compile(r"root@[^:]+:[^#]+# ?$"),  # root@container:~#
        re.compile(r"[a-zA-Z0-9_.-]+@[^:]+:[^$#]+[$#] ?$"),  # user@host:~$
        re.compile(r"\(?.*\)?\s*PS\s+[^>]+> ?$"),  # PowerShell prompt like (base) PS C:\...>
    ]
    # potential dialog detection
    dialog_patterns = [
        re.compile(r"Y/N", re.IGNORECASE),  # Y/N anywhere in line
        re.compile(r"yes/no", re.IGNORECASE),  # yes/no anywhere in line
        re.compile(r":\s*$"),  # line ending with colon
        re.compile(r"\?\s*$"),  # line ending with question mark
    ]

    async def execute(self, **kwargs) -> Response:

        await self.agent.handle_intervention()  # wait for intervention and handle it, if paused
        self._output_dump_marker = ""
        self._output_dumped = False
        # Tool args may be rewritten for display (e.g., §§include spill placeholders).
        # Always execute with resolved runtime kwargs when provided.
        exec_args = dict(self.args)
        exec_args.update(kwargs)

        runtime = str(exec_args.get("runtime", "")).lower().strip()
        session = int(exec_args.get("session", 0))
        self.allow_running = bool(exec_args.get("allow_running", False))
        reset = bool(exec_args.get("reset", False) or runtime == "reset")
        code = ""
        max_input_chars = int(
            settings.get_effective_settings(self.agent).get("code_exec_max_input_chars", 60000)
        )

        if runtime in {"python", "nodejs", "terminal"}:
            code = self._coerce_code_arg(exec_args.get("code"))
            if not code.strip():
                info = (
                    "Code execution request ignored because the `code` argument is empty or missing. "
                    "Regenerate the tool call with complete content."
                )
                PrintStyle.warning(info)
                response = self.agent.read_prompt("fw.code.info.md", info=info)
                return Response(message=response, break_loop=False)

            if max_input_chars > 0 and len(code) > max_input_chars:
                info = (
                    f"Code payload too large ({len(code)} chars > "
                    f"A0_SET_code_exec_max_input_chars={max_input_chars}). "
                    "Split into smaller chunks and retry."
                )
                PrintStyle.warning(info)
                response = self.agent.read_prompt("fw.code.info.md", info=info)
                return Response(message=response, break_loop=False)

            if runtime == "python":
                syntax_error = self._python_preflight_syntax_error(code)
                if syntax_error:
                    info = (
                        "Python code failed preflight syntax check before execution. "
                        "The payload may be truncated or malformed. "
                        f"Details: {syntax_error}"
                    )
                    PrintStyle.warning(info)
                    response = self.agent.read_prompt("fw.code.info.md", info=info)
                    return Response(message=response, break_loop=False)
        elif runtime == "file":
            path = self._coerce_code_arg(exec_args.get("path")).strip()
            content = self._coerce_code_arg(exec_args.get("content"))
            append = bool(exec_args.get("append", False))
            allow_empty = bool(exec_args.get("allow_empty", False))

            if not path:
                info = (
                    "File write request ignored because `path` is empty. "
                    "Regenerate the tool call with a valid path."
                )
                PrintStyle.warning(info)
                response = self.agent.read_prompt("fw.code.info.md", info=info)
                return Response(message=response, break_loop=False)

            invalid_path_reason = self._validate_file_path(path)
            if invalid_path_reason:
                PrintStyle.warning(invalid_path_reason)
                response = self.agent.read_prompt("fw.code.info.md", info=invalid_path_reason)
                return Response(message=response, break_loop=False)

            if not allow_empty and not content:
                info = (
                    "File write request ignored because `content` is empty. "
                    "This prevents accidental truncation to zero bytes. "
                    "Regenerate with full content, or set `allow_empty=true` for an intentional clear."
                )
                PrintStyle.warning(info)
                response = self.agent.read_prompt("fw.code.info.md", info=info)
                return Response(message=response, break_loop=False)

            if max_input_chars > 0 and len(content) > max_input_chars:
                info = (
                    f"File content payload too large ({len(content)} chars > "
                    f"A0_SET_code_exec_max_input_chars={max_input_chars}). "
                    "Split into smaller chunks and retry."
                )
                PrintStyle.warning(info)
                response = self.agent.read_prompt("fw.code.info.md", info=info)
                return Response(message=response, break_loop=False)

            response, break_loop = await self.execute_file_write(
                path=path, content=content, append=append
            )
            return Response(message=response, break_loop=break_loop)

        if runtime == "python":
            response = await self.execute_python_code(
                code=code, session=session, reset=reset
            )
        elif runtime == "nodejs":
            response = await self.execute_nodejs_code(
                code=code, session=session, reset=reset
            )
        elif runtime == "terminal":
            set = settings.get_effective_settings(self.agent)
            if bool(set.get("code_exec_guard_repetitive_terminal_read_enabled", False)):
                repetitive_msg, repetitive_break = self._check_repetitive_terminal_command(
                    session=session, command=code
                )
                if repetitive_msg:
                    PrintStyle.warning(repetitive_msg)
                    response = self.agent.read_prompt("fw.code.info.md", info=repetitive_msg)
                    return Response(message=response, break_loop=repetitive_break)
            if bool(set.get("code_exec_guard_simple_cat_direct_read_enabled", False)):
                cat_path = self._extract_simple_cat_path(code)
                if cat_path:
                    response, break_loop = await self.execute_file_read(path=cat_path)
                    return Response(message=response, break_loop=break_loop)
            response = await self.execute_terminal_command(
                command=code, session=session, reset=reset
            )
        elif runtime == "output":
            response = await self.get_terminal_output(
                session=session, timeouts=self._get_timeouts(output_runtime=True)
            )
        elif runtime == "reset":
            response = await self.reset_terminal(session=session)
        else:
            response = self.agent.read_prompt(
                "fw.code.runtime_wrong.md", runtime=runtime
            )

        if not response:
            response = self.agent.read_prompt(
                "fw.code.info.md", info=self.agent.read_prompt("fw.code.no_output.md")
            )
        return Response(message=response, break_loop=False)

    def get_log_object(self):
        return self.agent.context.log.log(
            type="code_exe",
            heading=self.get_heading(),
            content="",
            kvps=self.args,
        )

    def get_heading(self, text: str = ""):
        if not text:
            text = f"{self.name} - {self.args['runtime'] if 'runtime' in self.args else 'unknown'}"
        # text = truncate_text_string(text, 60) # don't truncate here, log.py takes care of it
        session = self.args.get("session", None)
        session_text = f"[{session}] " if session or session == 0 else ""
        return f"icon://terminal {session_text}{text}"

    async def after_execution(self, response, **kwargs):
        self.agent.hist_add_tool_result(self.name, response.message, **(response.additional or {}))

    async def prepare_state(self, reset=False, session: int | None = None):
        self.state: State | None = self.agent.get_data("_cet_state")
        # always reset state when ssh_enabled changes
        if not self.state or self.state.ssh_enabled != self.agent.config.code_exec_ssh_enabled:
            # initialize shells dictionary if not exists
            shells: dict[int, ShellWrap] = {}
        else:
            shells = self.state.shells.copy()

        # Only reset the specified session if provided
        if reset and session is not None and session in shells:
            await shells[session].session.close()
            del shells[session]
        elif reset and not session:
            # Close all sessions if full reset requested
            for s in list(shells.keys()):
                await shells[s].session.close()
            shells = {}

        # initialize local or remote interactive shell interface for session 0 if needed
        if session is not None and session not in shells:
            cwd = await self.ensure_cwd()
            if self.agent.config.code_exec_ssh_enabled:
                pswd = (
                    self.agent.config.code_exec_ssh_pass
                    if self.agent.config.code_exec_ssh_pass
                    else await rfc_exchange.get_root_password()
                )
                shell = SSHInteractiveSession(
                    self.agent.context.log,
                    self.agent.config.code_exec_ssh_addr,
                    self.agent.config.code_exec_ssh_port,
                    self.agent.config.code_exec_ssh_user,
                    pswd,
                    cwd=cwd,
                )
            else:
                shell = LocalInteractiveSession(cwd=cwd)

            shells[session] = ShellWrap(id=session, session=shell, running=False)
            await shell.connect()

        self.state = State(shells=shells, ssh_enabled=self.agent.config.code_exec_ssh_enabled)
        self.agent.set_data("_cet_state", self.state)
        return self.state

    async def execute_python_code(self, session: int, code: str, reset: bool = False):
        escaped_code = shlex.quote(code)
        command = f"ipython -c {escaped_code}"
        prefix = "python> " + self.format_command_for_output(code) + "\n\n"
        return await self.terminal_session(session, command, reset, prefix)

    async def execute_nodejs_code(self, session: int, code: str, reset: bool = False):
        escaped_code = shlex.quote(code)
        command = f"node /exe/node_eval.js {escaped_code}"
        prefix = "node> " + self.format_command_for_output(code) + "\n\n"
        return await self.terminal_session(session, command, reset, prefix)

    async def execute_terminal_command(
        self, session: int, command: str, reset: bool = False
    ):
        set = settings.get_effective_settings(self.agent)
        guard_unterminated_heredoc = bool(
            set.get("code_exec_guard_unterminated_heredoc_enabled", False)
        )
        guard_unbalanced_shell_quote = bool(
            set.get("code_exec_guard_unbalanced_shell_quote_enabled", False)
        )
        prefer_python_file_write = bool(
            set.get("code_exec_prefer_python_file_write", False)
        )
        if prefer_python_file_write and self._has_heredoc(command):
            unterminated_marker = (
                self._find_unterminated_heredoc_marker(command)
                if guard_unterminated_heredoc
                else None
            )
            if unterminated_marker:
                info = (
                    "Detected an unterminated heredoc in terminal command "
                    f"(missing closing marker `{unterminated_marker}` on its own line). "
                    "The command appears truncated and was not executed. "
                    "Retry with smaller chunks, or use runtime='python' with shorter content chunks."
                )
                PrintStyle.warning(info)
                return self.agent.read_prompt("fw.code.info.md", info=info)

            converted_python = self._convert_simple_cat_heredoc_to_python(command)
            if converted_python:
                PrintStyle.info(
                    "Converted terminal heredoc write to python file write due to policy."
                )
                return await self.execute_python_code(
                    session=session, code=converted_python, reset=reset
                )

            info = (
                "Heredoc terminal writes are disabled by policy "
                "(A0_SET_code_exec_prefer_python_file_write=true). "
                "Use runtime='python' to write file content instead of terminal heredoc."
            )
            PrintStyle.warning(info)
            return self.agent.read_prompt("fw.code.info.md", info=info)

        unterminated_marker = (
            self._find_unterminated_heredoc_marker(command)
            if guard_unterminated_heredoc
            else None
        )
        if unterminated_marker:
            info = (
                "Detected an unterminated heredoc in terminal command "
                f"(missing closing marker `{unterminated_marker}` on its own line). "
                "The command appears truncated and was not executed. "
                "Retry with smaller chunks, or use python runtime to write file content safely."
            )
            PrintStyle.warning(info)
            return self.agent.read_prompt("fw.code.info.md", info=info)
        quote_error = (
            self._find_unbalanced_shell_quote_error(command)
            if guard_unbalanced_shell_quote
            else None
        )
        if quote_error:
            info = (
                "Detected malformed shell quoting in terminal command; "
                "the command appears truncated and was not executed. "
                f"Details: {quote_error}. "
                "Regenerate the command with balanced quotes."
            )
            PrintStyle.warning(info)
            return self.agent.read_prompt("fw.code.info.md", info=info)
        prefix = ("bash>" if not runtime.is_windows() or self.agent.config.code_exec_ssh_enabled else "PS>") + self.format_command_for_output(command) + "\n\n"
        return await self.terminal_session(session, command, reset, prefix)

    async def terminal_session(
        self, session: int, command: str, reset: bool = False, prefix: str = "", timeouts: dict | None = None
    ):

        self.state = await self.prepare_state(reset=reset, session=session)

        await self.agent.handle_intervention()  # wait for intervention and handle it, if paused

        # Check if session is running and handle it
        if not self.allow_running:
            if response := await self.handle_running_session(session):
                return response
        
        # try again on lost connection
        for i in range(2):
            try:

                self.state.shells[session].running = True
                await self.state.shells[session].session.send_command(command)

                locl = (
                    " (local)"
                    if isinstance(self.state.shells[session].session, LocalInteractiveSession)
                    else (
                        " (remote)"
                        if isinstance(self.state.shells[session].session, SSHInteractiveSession)
                        else " (unknown)"
                    )
                )

                PrintStyle(
                    background_color="white", font_color="#1B4F72", bold=True
                ).print(f"{self.agent.agent_name} code execution output{locl}")
                return await self.get_terminal_output(
                    session=session,
                    prefix=prefix,
                    timeouts=(timeouts or self._get_timeouts(output_runtime=False)),
                )

            except Exception as e:
                if i == 1:
                    # try again on lost connection
                    PrintStyle.error(str(e))
                    await self.prepare_state(reset=True, session=session)
                    continue
                else:
                    raise e

    def format_command_for_output(self, command: str):
        # truncate long commands
        short_cmd = command[:200]
        # normalize whitespace for cleaner output
        short_cmd = " ".join(short_cmd.split())
        # replace any sequence of ', ", or ` with a single '
        # short_cmd = re.sub(r"['\"`]+", "'", short_cmd) # no need anymore
        # final length
        short_cmd = truncate_text_string(short_cmd, 100)
        return f"{short_cmd}"

    async def get_terminal_output(
        self,
        session=0,
        reset_full_output=True,
        first_output_timeout=30,  # Wait up to x seconds for first output
        between_output_timeout=15,  # Wait up to x seconds between outputs
        dialog_timeout=5,  # potential dialog detection timeout
        max_exec_timeout=180,  # hard cap on total runtime
        sleep_time=0.1,
        prefix="",
        timeouts: dict | None = None,
    ):

        # if not self.state:
        self.state = await self.prepare_state(session=session)

        # Override timeouts if a dict is provided
        if timeouts:
            first_output_timeout = timeouts.get("first_output_timeout", first_output_timeout)
            between_output_timeout = timeouts.get("between_output_timeout", between_output_timeout)
            dialog_timeout = timeouts.get("dialog_timeout", dialog_timeout)
            max_exec_timeout = timeouts.get("max_exec_timeout", max_exec_timeout)

        start_time = time.time()
        last_output_time = start_time
        full_output = ""
        truncated_output = ""
        got_output = False

        # if prefix, log right away
        if prefix:
            self.log.update(content=prefix)

        while True:
            await asyncio.sleep(sleep_time)
            full_output, partial_output = await self.state.shells[session].session.read_output(
                timeout=1, reset_full_output=reset_full_output
            )
            reset_full_output = False  # only reset once

            await self.agent.handle_intervention()

            now = time.time()
            if partial_output:
                PrintStyle(font_color="#85C1E9").stream(partial_output)
                # full_output += partial_output # Append new output
                truncated_output = self.fix_full_output(full_output)
                self.set_progress(truncated_output)
                heading = self.get_heading_from_output(truncated_output, 0)
                self.log.update(content=prefix + truncated_output, heading=heading)
                last_output_time = now
                got_output = True

                # Check for shell prompt at the end of output
                last_lines = (
                    truncated_output.splitlines()[-3:] if truncated_output else []
                )
                last_lines.reverse()
                for idx, line in enumerate(last_lines):
                    for pat in self.prompt_patterns:
                        if pat.search(line.strip()):
                            PrintStyle.info(
                                "Detected shell prompt, returning output early."
                            )
                            last_lines.reverse()
                            heading = self.get_heading_from_output(
                                "\n".join(last_lines), idx + 1, True
                            )
                            self.log.update(heading=heading)
                            self.mark_session_idle(session)
                            return truncated_output

            # Check for max execution time
            if now - start_time > max_exec_timeout:
                sysinfo = self.agent.read_prompt(
                    "fw.code.max_time.md", timeout=max_exec_timeout
                )
                response = self.agent.read_prompt("fw.code.info.md", info=sysinfo)
                if truncated_output:
                    response = truncated_output + "\n\n" + response
                PrintStyle.warning(sysinfo)
                heading = self.get_heading_from_output(truncated_output, 0)
                self.log.update(content=prefix + response, heading=heading)
                return response

            # Waiting for first output
            if not got_output:
                if now - start_time > first_output_timeout:
                    sysinfo = self.agent.read_prompt(
                        "fw.code.no_out_time.md", timeout=first_output_timeout
                    )
                    response = self.agent.read_prompt("fw.code.info.md", info=sysinfo)
                    PrintStyle.warning(sysinfo)
                    self.log.update(content=prefix + response)
                    return response
            else:
                # Waiting for more output after first output
                if now - last_output_time > between_output_timeout:
                    sysinfo = self.agent.read_prompt(
                        "fw.code.pause_time.md", timeout=between_output_timeout
                    )
                    response = self.agent.read_prompt("fw.code.info.md", info=sysinfo)
                    if truncated_output:
                        response = truncated_output + "\n\n" + response
                    PrintStyle.warning(sysinfo)
                    heading = self.get_heading_from_output(truncated_output, 0)
                    self.log.update(content=prefix + response, heading=heading)
                    return response

                # potential dialog detection
                if now - last_output_time > dialog_timeout:
                    # Check for dialog prompt at the end of output
                    last_lines = (
                        truncated_output.splitlines()[-2:] if truncated_output else []
                    )
                    for line in last_lines:
                        for pat in self.dialog_patterns:
                            if pat.search(line.strip()):
                                PrintStyle.info(
                                    "Detected dialog prompt, returning output early."
                                )

                                sysinfo = self.agent.read_prompt(
                                    "fw.code.pause_dialog.md", timeout=dialog_timeout
                                )
                                response = self.agent.read_prompt(
                                    "fw.code.info.md", info=sysinfo
                                )
                                if truncated_output:
                                    response = truncated_output + "\n\n" + response
                                PrintStyle.warning(sysinfo)
                                heading = self.get_heading_from_output(
                                    truncated_output, 0
                                )
                                self.log.update(
                                    content=prefix + response, heading=heading
                                )
                                return response

    async def handle_running_session(
        self,
        session=0,
        reset_full_output=True, 
        prefix=""
    ):
        if not self.state or session not in self.state.shells:
            return None
        if not self.state.shells[session].running:
            return None
        
        full_output, _ = await self.state.shells[session].session.read_output(
            timeout=1, reset_full_output=reset_full_output
        )
        truncated_output = self.fix_full_output(full_output)
        self.set_progress(truncated_output)
        heading = self.get_heading_from_output(truncated_output, 0)

        last_lines = (
            truncated_output.splitlines()[-3:] if truncated_output else []
        )
        last_lines.reverse()
        for idx, line in enumerate(last_lines):
            for pat in self.prompt_patterns:
                if pat.search(line.strip()):
                    PrintStyle.info(
                        "Detected shell prompt, returning output early."
                    )
                    self.mark_session_idle(session)
                    return None

        has_dialog = False 
        for line in last_lines:
            for pat in self.dialog_patterns:
                if pat.search(line.strip()):
                    has_dialog = True
                    break
            if has_dialog:
                break

        if has_dialog:
            sys_info = self.agent.read_prompt("fw.code.pause_dialog.md", timeout=1)       
        else:
            sys_info = self.agent.read_prompt("fw.code.running.md", session=session)

        response = self.agent.read_prompt("fw.code.info.md", info=sys_info)
        if truncated_output:
            response = truncated_output + "\n\n" + response
        PrintStyle(font_color="#FFA500", bold=True).print(response)
        self.log.update(content=prefix + response, heading=heading)
        return response
    
    def mark_session_idle(self, session: int = 0):
        # Mark session as idle - command finished
        if self.state and session in self.state.shells:
            self.state.shells[session].running = False

    async def reset_terminal(self, session=0, reason: str | None = None):
        # Print the reason for the reset to the console if provided
        if reason:
            PrintStyle(font_color="#FFA500", bold=True).print(
                f"Resetting terminal session {session}... Reason: {reason}"
            )
        else:
            PrintStyle(font_color="#FFA500", bold=True).print(
                f"Resetting terminal session {session}..."
            )

        # Only reset the specified session while preserving others
        await self.prepare_state(reset=True, session=session)
        response = self.agent.read_prompt(
            "fw.code.info.md", info=self.agent.read_prompt("fw.code.reset.md")
        )
        self.log.update(content=response)
        return response

    def get_heading_from_output(self, output: str, skip_lines=0, done=False):
        done_icon = " icon://done_all" if done else ""

        if not output:
            return self.get_heading() + done_icon

        # find last non-empty line with skip
        lines = output.splitlines()
        # Start from len(lines) - skip_lines - 1 down to 0
        for i in range(len(lines) - skip_lines - 1, -1, -1):
            line = lines[i].strip()
            if not line:
                continue
            return self.get_heading(line) + done_icon

        return self.get_heading() + done_icon

    def fix_full_output(self, output: str):
        # remove any single byte \xXX escapes
        output = re.sub(r"(?<!\\)\\x[0-9A-Fa-f]{2}", "", output)
        output = self._strip_runtime_noise_lines(output)
        # Strip every line of output before truncation
        # output = "\n".join(line.strip() for line in output.splitlines())
        set = settings.get_effective_settings(self.agent)
        max_chars = int(set.get("code_exec_output_max_chars", 1000000))
        auto_dump = bool(set.get("code_exec_auto_dump_large_output", True))
        dump_dir = str(set.get("code_exec_dump_dir", "usr/tmp/code_exec"))

        if max_chars > 0 and len(output) > max_chars and auto_dump and not self._output_dumped:
            timestamp = int(time.time() * 1000)
            session = self.args.get("session", 0)
            filename = f"code_exec_output_s{session}_{timestamp}.log"
            rel_path = os.path.join(dump_dir, filename)
            files.write_file(rel_path, output)
            self._output_dump_marker = (
                f"\n\n[Large output saved to: {files.get_abs_path(rel_path)}]"
            )
            self._output_dumped = True

        output = truncate_text_agent(agent=self.agent, output=output, threshold=max_chars)
        if self._output_dump_marker:
            output += self._output_dump_marker
        return output

    async def execute_file_write(
        self, path: str, content: str, append: bool = False
    ) -> tuple[str, bool]:
        set = settings.get_effective_settings(self.agent)
        normalized = files.normalize_a0_path(path)
        mode = "a" if append else "w"
        abs_path = str(Path(normalized).resolve())
        deterministic_msg, deterministic_break = self._check_deterministic_critical_mode(
            abs_path=abs_path, operation="write"
        )
        if deterministic_msg:
            PrintStyle.warning(deterministic_msg)
            return self.agent.read_prompt("fw.code.info.md", info=deterministic_msg), deterministic_break
        if bool(set.get("code_exec_guard_same_file_op_ceiling_enabled", False)):
            op_ceiling_msg, op_ceiling_break = self._check_file_op_ceiling(
                abs_path=abs_path,
                operation="write",
            )
            if op_ceiling_msg:
                PrintStyle.warning(op_ceiling_msg)
                return self.agent.read_prompt("fw.code.info.md", info=op_ceiling_msg), op_ceiling_break
        if not append and bool(set.get("code_exec_guard_strategy_block_enabled", False)):
            blocked_msg, blocked_break = self._check_blocked_strategy(
                abs_path=abs_path, strategy="full_overwrite"
            )
            if blocked_msg:
                PrintStyle.warning(blocked_msg)
                return self.agent.read_prompt("fw.code.info.md", info=blocked_msg), blocked_break
        guard_break = False
        guard_msg = None
        if bool(set.get("code_exec_guard_regressive_overwrite_enabled", False)):
            guard_msg = self._get_regressive_overwrite_guard(
                abs_path=abs_path, content=content, append=append
            )
        if guard_msg:
            if bool(set.get("code_exec_guard_strategy_block_enabled", False)):
                self._block_strategy(abs_path=abs_path, strategy="full_overwrite")
            PrintStyle.warning(guard_msg)
            guard_break = self._should_break_after_guard(abs_path)
            return self.agent.read_prompt("fw.code.info.md", info=guard_msg), guard_break

        try:
            target = Path(normalized)
            if target.exists() and target.is_dir():
                info = (
                    f"File write rejected: target path is a directory ({abs_path}). "
                    "Regenerate the tool call with a concrete file path."
                )
                PrintStyle.warning(info)
                return self.agent.read_prompt("fw.code.info.md", info=info), False
            target.parent.mkdir(parents=True, exist_ok=True)
            # Unescape content: model/serialization sometimes emits literal \n instead of newlines.
            # Preserve \\n (literal backslash-n) by escaping \\ first.
            content = self._unescape_file_content(content)
            with target.open(mode, encoding="utf-8") as f:
                f.write(content)
            if not append and bool(set.get("code_exec_guard_write_verify_enabled", False)):
                expected_bytes = len(content.encode("utf-8"))
                actual_bytes = target.stat().st_size
                if actual_bytes != expected_bytes:
                    info = (
                        "[WRITE_GUARD:VERIFY_FAILED] "
                        f"File write verification failed for {abs_path}: "
                        f"expected {expected_bytes} bytes, got {actual_bytes} bytes. "
                        "Do not retry full overwrite blindly; read current file and repair only missing sections."
                    )
                    PrintStyle.warning(info)
                    self._mark_recovery_required(abs_path)
                    return self.agent.read_prompt("fw.code.info.md", info=info), False
            op = "Appended to" if append else "Wrote"
            info = f"{op} file: {abs_path} ({len(content)} chars)."
            PrintStyle.info(info)
            self._record_file_write_success(abs_path=abs_path, content=content, append=append)
            if (
                bool(set.get("code_exec_deterministic_critical_mode_enabled", False))
                and self._is_critical_file(abs_path)
                and bool(set.get("code_exec_deterministic_critical_break_after_write", True))
            ):
                info += (
                    "\n\n[DETERMINISTIC_CRITICAL:COMPLETE] "
                    "Critical-file deterministic flow completed (read/transform/write/verify). "
                    "Stop this turn and report results."
                )
                return self.agent.read_prompt("fw.code.info.md", info=info), True
            return self.agent.read_prompt("fw.code.info.md", info=info), False
        except Exception as e:
            info = f"File write failed for {abs_path}: {e}"
            PrintStyle.error(info)
            return self.agent.read_prompt("fw.code.info.md", info=info), False

    async def execute_file_read(self, path: str) -> tuple[str, bool]:
        set = settings.get_effective_settings(self.agent)
        normalized = files.normalize_a0_path(path)
        abs_path = str(Path(normalized).resolve())
        deterministic_msg, deterministic_break = self._check_deterministic_critical_mode(
            abs_path=abs_path, operation="read"
        )
        if deterministic_msg:
            PrintStyle.warning(deterministic_msg)
            return self.agent.read_prompt("fw.code.info.md", info=deterministic_msg), deterministic_break
        if bool(set.get("code_exec_guard_same_file_op_ceiling_enabled", False)):
            op_ceiling_msg, op_ceiling_break = self._check_file_op_ceiling(
                abs_path=abs_path,
                operation="read",
            )
            if op_ceiling_msg:
                PrintStyle.warning(op_ceiling_msg)
                return self.agent.read_prompt("fw.code.info.md", info=op_ceiling_msg), op_ceiling_break
        if bool(set.get("code_exec_guard_strategy_block_enabled", False)):
            blocked_msg, blocked_break = self._check_blocked_strategy(
                abs_path=abs_path, strategy="same_path_read"
            )
            if blocked_msg:
                PrintStyle.warning(blocked_msg)
                return self.agent.read_prompt("fw.code.info.md", info=blocked_msg), blocked_break
        try:
            target = Path(normalized)
            if not target.exists():
                info = f"File read failed for {abs_path}: file does not exist."
                PrintStyle.warning(info)
                return self.agent.read_prompt("fw.code.info.md", info=info), False
            if target.is_dir():
                info = f"File read failed for {abs_path}: target is a directory."
                PrintStyle.warning(info)
                return self.agent.read_prompt("fw.code.info.md", info=info), False

            content = target.read_text(encoding="utf-8")
            if bool(set.get("code_exec_guard_repetitive_file_read_enabled", False)):
                repetitive_msg, repetitive_break = self._check_repetitive_file_read(
                    abs_path=abs_path, content=content
                )
                if repetitive_msg:
                    if bool(set.get("code_exec_guard_strategy_block_enabled", False)):
                        self._block_strategy(abs_path=abs_path, strategy="same_path_read")
                    PrintStyle.warning(repetitive_msg)
                    return self.agent.read_prompt("fw.code.info.md", info=repetitive_msg), repetitive_break

            info = (
                f"Read file: {abs_path} ({len(content)} chars).\n\n"
                f"{content}"
            )
            return self.agent.read_prompt("fw.code.info.md", info=info), False
        except Exception as e:
            info = f"File read failed for {abs_path}: {e}"
            PrintStyle.error(info)
            return self.agent.read_prompt("fw.code.info.md", info=info), False

    def _coerce_code_arg(self, value: object) -> str:
        if value is None:
            return ""
        return str(value)

    def _unescape_file_content(self, content: str) -> str:
        """Convert literal \\n, \\t, \\r in content to real newlines/tabs/cr.
        Preserves \\\\n (literal backslash-n) by escaping \\ first."""
        if not content:
            return content
        _PL = "\uE000"  # private-use placeholder, unlikely in normal text
        s = content.replace("\\\\", _PL)
        s = s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
        return s.replace(_PL, "\\")

    def _validate_file_path(self, path: str) -> str | None:
        candidate = path.strip()
        normalized = files.normalize_a0_path(candidate)
        target = Path(normalized)

        if candidate in {"/", ".", ".."}:
            return (
                "File write request ignored because `path` points to a directory/root "
                f"({candidate!r}). Regenerate with a concrete file path."
            )

        if candidate.endswith("/") or target.name in {"", ".", ".."}:
            return (
                "File write request ignored because `path` looks like a directory, not a file. "
                f"Provided path: {candidate!r}."
            )

        # Guard against common truncation artifacts such as '/a' or '/x'.
        if target.is_absolute() and len(target.parts) <= 2:
            return (
                "File write request ignored because `path` looks truncated/unsafe "
                f"({candidate!r}). Regenerate with the full absolute file path."
            )

        return None

    def _get_regressive_overwrite_guard(
        self, abs_path: str, content: str, append: bool
    ) -> str | None:
        if append:
            return None
        meta: dict = self.agent.get_data("_cet_file_write_meta") or {}
        prev = meta.get(abs_path)
        if not prev:
            return None

        prev_len = int(prev.get("chars", 0))
        prev_sha = str(prev.get("sha256", ""))
        prev_at = float(prev.get("ts", 0))
        new_len = len(content)
        new_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        age_seconds = int(max(0, time.time() - prev_at))

        # Idempotent rewrite of same payload is safe.
        if new_sha == prev_sha:
            return None

        # Once in recovery mode, force repair flow instead of repeated full overwrite.
        if prev.get("recovery_required"):
            self._mark_recovery_required(abs_path)
            snapshot_hint = str(prev.get("snapshot_path", ""))
            snapshot_text = (
                f" Last stable snapshot: {snapshot_hint}."
                if snapshot_hint
                else ""
            )
            return (
                "[WRITE_GUARD:RECOVERY_MODE] "
                f"Full overwrite blocked for {abs_path} while recovery mode is active. "
                "Read current file and repair incrementally (append=true or targeted patch)."
                + snapshot_text
            )

        # Guard against degradation loops where repeated full rewrites get smaller.
        if age_seconds <= 1800 and prev_len >= 500:
            if new_len <= int(prev_len * 0.85) and (prev_len - new_len) >= 200:
                self._mark_recovery_required(abs_path)
                snapshot_hint = str(prev.get("snapshot_path", ""))
                snapshot_text = (
                    f" Last stable snapshot: {snapshot_hint}."
                    if snapshot_hint
                    else ""
                )
                return (
                    "[WRITE_GUARD:REGRESSIVE_OVERWRITE] "
                    "Rejected likely regressive full overwrite for "
                    f"{abs_path}: previous successful write was {prev_len} chars "
                    f"{age_seconds}s ago, new payload is {new_len} chars. "
                    "Read current file and repair missing sections; avoid repeated append=false full rewrites."
                    + snapshot_text
                )
        return None

    def _record_file_write_success(self, abs_path: str, content: str, append: bool):
        meta: dict = self.agent.get_data("_cet_file_write_meta") or {}
        snapshot_path = self._write_snapshot(abs_path=abs_path, content=content)
        prev = meta.get(abs_path) or {}
        meta[abs_path] = {
            "chars": len(content),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "ts": time.time(),
            "snapshot_path": snapshot_path,
            "recovery_required": False if append else bool(prev.get("recovery_required", False)),
            "guard_reject_count": 0 if not append else int(prev.get("guard_reject_count", 0)),
        }
        if append:
            # Successful append is part of recovery flow; keep full-overwrite guard state.
            meta[abs_path]["recovery_required"] = bool(prev.get("recovery_required", False))
        else:
            # Successful full write clears recovery mode.
            meta[abs_path]["recovery_required"] = False
            meta[abs_path]["guard_reject_count"] = 0
            self._clear_blocked_strategy(abs_path=abs_path, strategy="full_overwrite")
        self.agent.set_data("_cet_file_write_meta", meta)

    def _mark_recovery_required(self, abs_path: str):
        meta: dict = self.agent.get_data("_cet_file_write_meta") or {}
        prev = meta.get(abs_path) or {}
        now = time.time()
        set = settings.get_effective_settings(self.agent)
        retry_window_seconds = int(
            set.get("code_exec_regressive_guard_retry_window_seconds", 120)
        )
        if retry_window_seconds < 1:
            retry_window_seconds = 1
        last_reject = float(prev.get("last_reject_ts", 0) or 0)
        # Treat stale retries as a new turn window.
        if last_reject and (now - last_reject) > retry_window_seconds:
            count = 1
        else:
            count = int(prev.get("guard_reject_count", 0)) + 1
        prev["guard_reject_count"] = count
        prev["recovery_required"] = True
        prev["last_reject_ts"] = now
        meta[abs_path] = prev
        self.agent.set_data("_cet_file_write_meta", meta)

    def _should_break_after_guard(self, abs_path: str) -> bool:
        meta: dict = self.agent.get_data("_cet_file_write_meta") or {}
        prev = meta.get(abs_path) or {}
        count = int(prev.get("guard_reject_count", 0))
        set = settings.get_effective_settings(self.agent)
        retry_threshold = int(
            set.get("code_exec_regressive_guard_retry_threshold", 3)
        )
        if retry_threshold < 1:
            retry_threshold = 1
        # Stop the current loop after repeated guarded failures on the same file.
        if count >= retry_threshold:
            PrintStyle.warning(
                "[WRITE_GUARD:TURN_ABORT] Too many guarded overwrite retries; breaking loop for user intervention."
            )
            return True
        return False

    def _is_critical_file(self, abs_path: str) -> bool:
        set = settings.get_effective_settings(self.agent)
        patterns_raw = str(
            set.get("code_exec_deterministic_critical_patterns", "Today.md,*/Today.md")
        )
        patterns = [p.strip() for p in patterns_raw.split(",") if p.strip()]
        if not patterns:
            return False
        name = Path(abs_path).name
        posix = Path(abs_path).as_posix()
        for pattern in patterns:
            if "*" in pattern:
                regex = "^" + re.escape(pattern).replace("\\*", ".*") + "$"
                if re.match(regex, posix):
                    return True
                continue
            if pattern == name or posix.endswith("/" + pattern) or posix == pattern:
                return True
        return False

    def _check_deterministic_critical_mode(
        self, abs_path: str, operation: str
    ) -> tuple[str | None, bool]:
        set = settings.get_effective_settings(self.agent)
        if not bool(set.get("code_exec_deterministic_critical_mode_enabled", False)):
            return None, False
        if not self._is_critical_file(abs_path):
            return None, False

        window_seconds = int(set.get("code_exec_deterministic_critical_window_seconds", 900))
        if window_seconds < 1:
            window_seconds = 1
        now = time.time()
        state: dict = self.agent.get_data("_cet_deterministic_critical_state") or {}
        entry = state.get(abs_path, {"read_count": 0, "write_count": 0, "ts": now})
        last_ts = float(entry.get("ts", 0) or 0)
        if (now - last_ts) > window_seconds:
            entry = {"read_count": 0, "write_count": 0, "ts": now}

        read_count = int(entry.get("read_count", 0) or 0)
        write_count = int(entry.get("write_count", 0) or 0)

        if operation == "read":
            if write_count > 0:
                return (
                    "[DETERMINISTIC_CRITICAL:POST_WRITE_READ_BLOCKED] "
                    f"Blocked additional read for critical file {abs_path} after write. "
                    "Deterministic mode requires reporting results instead of re-reading in this turn.",
                    True,
                )
            if read_count >= 1:
                return (
                    "[DETERMINISTIC_CRITICAL:READ_ONCE] "
                    f"Blocked repeated read for critical file {abs_path}. "
                    "Use previously retrieved content for transform/write.",
                    True,
                )
            entry["read_count"] = read_count + 1
        elif operation == "write":
            if write_count >= 1:
                return (
                    "[DETERMINISTIC_CRITICAL:WRITE_ONCE] "
                    f"Blocked repeated write for critical file {abs_path}. "
                    "Deterministic mode allows one write per window.",
                    True,
                )
            entry["write_count"] = write_count + 1

        entry["ts"] = now
        state[abs_path] = entry
        self.agent.set_data("_cet_deterministic_critical_state", state)
        return None, False

    def _check_file_op_ceiling(self, abs_path: str, operation: str) -> tuple[str | None, bool]:
        set = settings.get_effective_settings(self.agent)
        read_ceiling = int(set.get("code_exec_same_file_read_ceiling", 2))
        write_ceiling = int(set.get("code_exec_same_file_write_ceiling", 2))
        window_seconds = int(set.get("code_exec_file_op_window_seconds", 180))
        if window_seconds < 1:
            window_seconds = 1

        if operation == "read":
            ceiling = read_ceiling
        else:
            ceiling = write_ceiling
        if ceiling < 1:
            return None, False

        key = f"{operation}:{abs_path}"
        now = time.time()
        meta: dict = self.agent.get_data("_cet_file_op_counts") or {}
        prev = meta.get(key, {})
        last_ts = float(prev.get("ts", 0) or 0)
        count = int(prev.get("count", 0) or 0)
        if (now - last_ts) <= window_seconds:
            count += 1
        else:
            count = 1
        meta[key] = {"count": count, "ts": now}
        self.agent.set_data("_cet_file_op_counts", meta)

        if count > ceiling:
            tag = (
                "[READ_GUARD:SAME_FILE_CEILING]"
                if operation == "read"
                else "[WRITE_GUARD:SAME_FILE_CEILING]"
            )
            return (
                f"{tag} Blocked repeated {operation} operations for {abs_path} "
                f"(count={count}, ceiling={ceiling}, window={window_seconds}s). "
                "Do not repeat this operation again in this turn; use existing output and switch strategy.",
                True,
            )
        return None, False

    def _check_blocked_strategy(self, abs_path: str, strategy: str) -> tuple[str | None, bool]:
        meta: dict = self.agent.get_data("_cet_strategy_blocks") or {}
        key = f"{abs_path}:{strategy}"
        blocked = meta.get(key)
        if not blocked:
            return None, False
        set = settings.get_effective_settings(self.agent)
        ttl_seconds = int(set.get("code_exec_strategy_block_ttl_seconds", 300))
        if ttl_seconds < 1:
            ttl_seconds = 1
        blocked_at = float(blocked.get("ts", 0) or 0)
        age = int(max(0, time.time() - blocked_at))
        if age > ttl_seconds:
            meta.pop(key, None)
            self.agent.set_data("_cet_strategy_blocks", meta)
            return None, False
        return (
            "[STRATEGY_GUARD:ALTERNATE_REQUIRED] "
            f"Blocked strategy `{strategy}` for {abs_path} after prior guardrail trigger "
            f"({age}s ago). Use an alternate approach in this turn.",
            True,
        )

    def _block_strategy(self, abs_path: str, strategy: str):
        meta: dict = self.agent.get_data("_cet_strategy_blocks") or {}
        key = f"{abs_path}:{strategy}"
        meta[key] = {"ts": time.time()}
        self.agent.set_data("_cet_strategy_blocks", meta)

    def _clear_blocked_strategy(self, abs_path: str, strategy: str):
        meta: dict = self.agent.get_data("_cet_strategy_blocks") or {}
        key = f"{abs_path}:{strategy}"
        if key in meta:
            meta.pop(key, None)
            self.agent.set_data("_cet_strategy_blocks", meta)

    def _write_snapshot(self, abs_path: str, content: str) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        name = Path(abs_path).name or "file"
        snap_dir = Path("/a0/usr/tmp/code_exec_snapshots")
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_file = snap_dir / f"{name}.{digest}.txt"
        snap_file.write_text(content, encoding="utf-8")
        return str(snap_file)

    def _python_preflight_syntax_error(self, code: str) -> str | None:
        try:
            compile(code, "<code_execution_tool>", "exec")
            return None
        except SyntaxError as e:
            return f"{e.msg} (line {e.lineno}, offset {e.offset})"

    def _has_heredoc(self, command: str) -> bool:
        return re.search(r"<<-?\s*(['\"]?)[A-Za-z_][A-Za-z0-9_]*\1", command) is not None

    def _convert_simple_cat_heredoc_to_python(self, command: str) -> str | None:
        """
        Convert a simple single heredoc write command to Python.
        Supported forms:
          cat > /path/file << 'EOF'
          ...
          EOF
          cat >> /path/file << EOF
          ...
          EOF
        """
        lines = command.splitlines()
        if len(lines) < 2:
            return None

        opener = re.match(
            r"^\s*cat\s*(>>|>)\s*(\S+)\s*<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\3\s*$",
            lines[0],
        )
        if not opener:
            return None

        op = opener.group(1)
        file_path = opener.group(2)
        marker = opener.group(4)
        marker_pattern = re.compile(rf"^[ \t]*{re.escape(marker)}[ \t]*$")

        closing_idx = None
        for idx in range(1, len(lines)):
            if marker_pattern.match(lines[idx]):
                closing_idx = idx
                break
        if closing_idx is None:
            return None

        content = "\n".join(lines[1:closing_idx])
        mode = "a" if op == ">>" else "w"
        return (
            "from pathlib import Path\n"
            f"path = Path({file_path!r})\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            f"with path.open({mode!r}, encoding='utf-8') as f:\n"
            f"    f.write({content!r})\n"
        )

    def _find_unterminated_heredoc_marker(self, command: str) -> str | None:
        # Guard against truncated heredocs (e.g., "... << 'EOF'" without a closing EOF line).
        opener_pattern = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
        lines = command.splitlines()
        if not lines:
            return None

        openers: list[tuple[str, int]] = []
        for idx, line in enumerate(lines):
            for match in opener_pattern.finditer(line):
                openers.append((match.group(2), idx))

        if not openers:
            return None

        for marker, start_idx in openers:
            marker_pattern = re.compile(rf"^[ \t]*{re.escape(marker)}[ \t]*$")
            closed = any(marker_pattern.match(line) for line in lines[start_idx + 1 :])
            if not closed:
                return marker
        return None

    def _find_unbalanced_shell_quote_error(self, command: str) -> str | None:
        # Catch common truncated command cases that leave shell waiting for input.
        try:
            shlex.split(command, posix=True)
            return None
        except ValueError as e:
            msg = str(e)
            if "No closing quotation" in msg:
                return msg
            return None

    def _get_timeouts(self, output_runtime: bool = False) -> dict[str, int]:
        defaults = OUTPUT_TIMEOUTS if output_runtime else CODE_EXEC_TIMEOUTS
        set = settings.get_effective_settings(self.agent)
        return {
            "first_output_timeout": int(
                set.get("code_exec_first_output_timeout", defaults["first_output_timeout"])
            ),
            "between_output_timeout": int(
                set.get(
                    "code_exec_between_output_timeout",
                    defaults["between_output_timeout"],
                )
            ),
            "max_exec_timeout": int(
                set.get("code_exec_max_exec_timeout", defaults["max_exec_timeout"])
            ),
            "dialog_timeout": int(
                set.get("code_exec_dialog_timeout", defaults["dialog_timeout"])
            ),
        }

    def _check_repetitive_terminal_command(
        self, session: int, command: str
    ) -> tuple[str | None, bool]:
        normalized = " ".join(command.split()).strip()
        if not normalized:
            return None, False
        # Focus on read-only commands that should not need repeated execution.
        if not self._is_read_only_terminal_command(normalized):
            return None, False

        now = time.time()
        key = f"s{session}:{normalized}"
        meta: dict = self.agent.get_data("_cet_terminal_repeat_meta") or {}
        prev = meta.get(key, {})
        last_ts = float(prev.get("ts", 0) or 0)
        count = int(prev.get("count", 0) or 0)
        if (now - last_ts) <= 90:
            count += 1
        else:
            count = 1
        meta[key] = {"count": count, "ts": now}
        self.agent.set_data("_cet_terminal_repeat_meta", meta)

        if count >= 4:
            return (
                "[TERMINAL_GUARD:REPETITIVE_READ] Repeated identical read-only terminal command "
                f"{count} times in a short window (`{normalized}`). "
                "Do not retry the same command again in this turn. Use the previous output and move to the next required step.",
                True,
            )
        return None, False

    def _check_repetitive_file_read(
        self, abs_path: str, content: str
    ) -> tuple[str | None, bool]:
        now = time.time()
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        key = f"file_read:{abs_path}:{sha}"
        meta: dict = self.agent.get_data("_cet_file_read_meta") or {}
        prev = meta.get(key, {})
        last_ts = float(prev.get("ts", 0) or 0)
        count = int(prev.get("count", 0) or 0)
        if (now - last_ts) <= 90:
            count += 1
        else:
            count = 1
        meta[key] = {"count": count, "ts": now}
        self.agent.set_data("_cet_file_read_meta", meta)
        if count >= 3:
            return (
                "[READ_GUARD:REPETITIVE_FILE_READ] Repeated identical file read "
                f"{count} times in a short window ({abs_path}). "
                "Use the already returned content and proceed to the next requested step.",
                True,
            )
        return None, False

    def _is_read_only_terminal_command(self, command: str) -> bool:
        prefixes = (
            "cat ",
            "head ",
            "tail ",
            "sed -n",
            "wc ",
            "ls ",
            "stat ",
            "grep ",
            "rg ",
            "find ",
        )
        return command.startswith(prefixes)

    def _extract_simple_cat_path(self, command: str) -> str | None:
        normalized = " ".join(command.split()).strip()
        m = re.match(r"^cat\s+([^\s|;&<>]+)$", normalized)
        if not m:
            return None
        return m.group(1)

    def _strip_runtime_noise_lines(self, output: str) -> str:
        noise_markers = (
            "DeprecationWarning: GitWildMatchPattern",
            "RequestsDependencyWarning: urllib3",
            "patterns = [pattern_factory(line) for line in lines if line]",
            "regex, include = self.pattern_to_regex(pattern)",
        )
        kept = []
        for line in output.splitlines():
            if any(marker in line for marker in noise_markers):
                continue
            kept.append(line)
        return "\n".join(kept)

    async def ensure_cwd(self) -> str | None:
        project_name = projects.get_context_project_name(self.agent.context)
        if project_name:
            path = projects.get_project_folder(project_name)
        else:
            set = settings.get_effective_settings(self.agent)
            path = set.get("workdir_path")

        if not path:
            return None

        normalized = files.normalize_a0_path(path)
        await runtime.call_development_function(make_dir, normalized)
        return normalized

def make_dir(path: str):
    import os
    os.makedirs(path, exist_ok=True)
        

        