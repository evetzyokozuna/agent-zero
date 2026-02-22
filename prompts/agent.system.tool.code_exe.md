### code_execution_tool

execute terminal commands python nodejs code for computation or software tasks
place code in "code" arg; escape carefully and indent properly
select "runtime" arg: "terminal" "python" "nodejs" "file" "output"
select "session" number, 0 default, others for multitasking
if code runs long, use runtime "output" to wait
use argument reset true on next call to kill previous process when stuck default false
use "pip" "npm" "apt-get" in "terminal" to install package
to output, use print() or console.log()
if tool outputs error, adjust code before retrying;
important: check code for placeholders or demo data; replace with real variables; don't reuse snippets
important: avoid very large inline code payloads; prefer chunked writes for large file content
important: respect A0_SET_code_exec_max_input_chars; if content is long, split it into multiple smaller tool calls
important: for file writes, prefer runtime "file" with path/content/append over heredoc or triple-quoted python
important: when replacing an entire file, do exactly one runtime "file" call with append=false and the full content; do not follow with extra overwrite calls unless user explicitly asks
important: if chunking is required, first chunk must be append=false and all remaining chunks must be append=true to the same path
important: after a write, verify using runtime "terminal" (wc -c and optional marker grep) and report byte count before making more write calls
important: if verification fails or output indicates partial content, regenerate missing content and repair with append=true; avoid repeated full rewrites
important: do not switch back to terminal heredoc for markdown/text file writes once runtime "file" is available
don't use with other tools except thoughts; wait for response before using others
check dependencies before running code
output may end with [SYSTEM: ...] information comming from framework, not terminal
usage:

1 execute terminal command

~~~json
{
    "thoughts": [
        "Need to do...",
        "Need to install...",
    ],
    "headline": "Installing zip package via terminal",
    "tool_name": "code_execution_tool",
    "tool_args": {
        "runtime": "terminal",
        "session": 0,
        "reset": false,
        "code": "apt-get install zip",
    }
}
~~~

2 execute python code

~~~json
{
    "thoughts": [
        "Need to do...",
        "I can use...",
        "Then I can...",
    ],
    "headline": "Executing Python code to check current directory",
    "tool_name": "code_execution_tool",
    "tool_args": {
        "runtime": "python",
        "session": 0,
        "reset": false,
        "code": "import os\nprint(os.getcwd())",
    }
}
~~~

3 execute nodejs code

~~~json
{
    "thoughts": [
        "Need to do...",
        "I can use...",
        "Then I can...",
    ],
    "headline": "Executing Javascript code to check current directory",
    "tool_name": "code_execution_tool",
    "tool_args": {
        "runtime": "nodejs",
        "session": 0,
        "reset": false,
        "code": "console.log(process.cwd());",
    }
}
~~~

4 wait for output with long-running scripts

~~~json
{
    "thoughts": [
        "Waiting for program to finish...",
    ],
    "headline": "Waiting for long-running program to complete",
    "tool_name": "code_execution_tool",
    "tool_args": {
        "runtime": "output",
        "session": 0,
    }
}
~~~

5 deterministic file write (preferred for markdown/text)

~~~json
{
    "thoughts": [
        "Need to write file content safely without heredoc/triple quotes.",
    ],
    "headline": "Write Today.md content",
    "tool_name": "code_execution_tool",
    "tool_args": {
        "runtime": "file",
        "path": "/a0/usr/workdir/evetz_restore/Today.md",
        "append": false,
        "content": "# Title\\n\\nBody text...",
    }
}
~~~

6 verify write result before any retry

~~~json
{
    "thoughts": [
        "Verify bytes before another write attempt.",
    ],
    "headline": "Verify Today.md write size",
    "tool_name": "code_execution_tool",
    "tool_args": {
        "runtime": "terminal",
        "session": 0,
        "reset": false,
        "code": "wc -c /a0/usr/workdir/evetz_restore/Today.md",
    }
}
~~~
