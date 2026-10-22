(() => {
  'use strict';
  const form = document.querySelector('#login-form, #register-form');
  if (!form) return;
  const message = document.querySelector('#auth-message');
  const submit = document.querySelector('#submit-button');
  const showMessage = (text, kind = 'error') => {
    message.textContent = text;
    message.className = `message ${kind}`;
    message.hidden = false;
  };
  document.querySelectorAll('[data-toggle-password]').forEach(button => button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.togglePassword);
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.textContent = show ? 'Hide' : 'Show';
    button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  }));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    message.hidden = true;
    const values = Object.fromEntries(new FormData(form).entries());
    if (form.id === 'register-form' && values.password.length < 10) {
      showMessage('Please choose a password with at least 10 characters.'); return;
    }
    submit.disabled = true;
    submit.textContent = form.id === 'login-form' ? 'Signing in…' : 'Creating account…';
    try {
      const endpoint = form.id === 'login-form' ? '/api/login' : '/api/register';
      const response = await fetch(endpoint, {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body:JSON.stringify(values)});
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'We could not complete that request. Please try again.');
      showMessage(form.id === 'login-form' ? 'Signed in successfully. Opening your workspace…' : 'Your account is ready. Opening your workspace…', 'success');
      window.location.assign('index.html');
    } catch (error) {
      const localFile = location.protocol === 'file:';
      showMessage(localFile ? 'This page must be opened through the local server. Extract the ZIP, run ./start.sh (or python3 server.py), then visit http://127.0.0.1:8080/login.html.' : (error.message || 'Unable to connect to the local server. Make sure it is running.'));
    } finally {
      submit.disabled = false;
      if (form.isConnected) submit.innerHTML = form.id === 'login-form' ? 'Log in <span aria-hidden="true">→</span>' : 'Create account <span aria-hidden="true">→</span>';
    }
  });
})();
