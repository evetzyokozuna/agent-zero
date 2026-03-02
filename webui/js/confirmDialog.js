// Custom confirmation dialog. CSS in /css/modals.css

const DIALOG_TYPES = {
  warning: { icon: 'warning', color: 'var(--color-warning, #f59e0b)' },
  danger: { icon: 'error', color: 'var(--color-error, #ef4444)' },
  info: { icon: 'info', color: 'var(--color-primary, #3b82f6)' }
};

export function showConfirmDialog(options) {
  const {
    title = 'Confirm',
    message = '',
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    type = 'warning'
  } = options;

  const typeConfig = DIALOG_TYPES[type] || DIALOG_TYPES.warning;

  return new Promise((resolve) => {
    // Create backdrop
    const backdrop = document.createElement('div');
    backdrop.className = 'confirm-dialog-backdrop';
    
    // Create dialog
    const dialog = document.createElement('div');
    dialog.className = 'confirm-dialog';
    dialog.innerHTML = `
      <div class="confirm-dialog-header">
        <span class="confirm-dialog-icon material-symbols-outlined" style="color: ${typeConfig.color}">${typeConfig.icon}</span>
        <span class="confirm-dialog-title">${title}</span>
      </div>
      <div class="confirm-dialog-body">${message}</div>
      <div class="confirm-dialog-footer">
        <button class="button cancel confirm-dialog-cancel">${cancelText}</button>
        <button class="button confirm confirm-dialog-confirm">${confirmText}</button>
      </div>
    `;

    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);

    // Show with animation
    requestAnimationFrame(() => {
      backdrop.classList.add('visible');
      dialog.querySelector('.confirm-dialog-cancel').focus();
    });

    // Close handler
    const close = (result) => {
      backdrop.classList.remove('visible');
      document.removeEventListener('keydown', handleKeydown);
      setTimeout(() => {
        backdrop.remove();
        resolve(result);
      }, 200);
    };

    // Event listeners
    dialog.querySelector('.confirm-dialog-cancel').addEventListener('click', () => close(false));
    dialog.querySelector('.confirm-dialog-confirm').addEventListener('click', () => close(true));
    backdrop.addEventListener('click', (e) => e.target === backdrop && close(false));

    // Keyboard handling
    const handleKeydown = (e) => {
      if (e.key === 'Escape') close(false);
      else if (e.key === 'Enter') close(true);
    };
    document.addEventListener('keydown', handleKeydown);
  });
}

export function showChoiceDialog(options) {
  const {
    title = 'Choose',
    message = '',
    choices = [],
    cancelId = null,
    type = 'info'
  } = options || {};

  const normalizedChoices = Array.isArray(choices)
    ? choices.filter((c) => c && c.id && c.label)
    : [];
  if (normalizedChoices.length === 0) {
    return Promise.resolve(null);
  }

  const typeConfig = DIALOG_TYPES[type] || DIALOG_TYPES.info;

  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'confirm-dialog-backdrop';

    const dialog = document.createElement('div');
    dialog.className = 'confirm-dialog';
    const choicesHtml = normalizedChoices
      .map((choice) => {
        const variant = choice.variant || 'cancel';
        return `<button class="button ${variant} confirm-dialog-choice" data-choice-id="${choice.id}">${choice.label}</button>`;
      })
      .join('');
    dialog.innerHTML = `
      <div class="confirm-dialog-header">
        <span class="confirm-dialog-icon material-symbols-outlined" style="color: ${typeConfig.color}">${typeConfig.icon}</span>
        <span class="confirm-dialog-title">${title}</span>
      </div>
      <div class="confirm-dialog-body">${message}</div>
      <div class="confirm-dialog-footer">
        ${choicesHtml}
      </div>
    `;

    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);

    requestAnimationFrame(() => {
      backdrop.classList.add('visible');
      dialog.querySelector('.confirm-dialog-choice')?.focus();
    });

    const close = (result) => {
      backdrop.classList.remove('visible');
      document.removeEventListener('keydown', handleKeydown);
      setTimeout(() => {
        backdrop.remove();
        resolve(result);
      }, 200);
    };

    dialog.querySelectorAll('.confirm-dialog-choice').forEach((btn) => {
      btn.addEventListener('click', () => {
        close(btn.getAttribute('data-choice-id'));
      });
    });
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close(cancelId);
    });

    const handleKeydown = (e) => {
      if (e.key === 'Escape') close(cancelId);
    };
    document.addEventListener('keydown', handleKeydown);
  });
}
