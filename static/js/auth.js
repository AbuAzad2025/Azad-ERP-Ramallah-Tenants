(function() {
  if (window.__AUTH_INIT__) return;
  window.__AUTH_INIT__ = true;

document.addEventListener('DOMContentLoaded', function () {
  const btn = document.getElementById('login-toggle-pass') || document.querySelector('.toggle-pass');
  const input = document.getElementById('login-password');
  if (btn && input) {
    btn.addEventListener('click', function () {
      const isText = input.getAttribute('type') === 'text';
      input.setAttribute('type', isText ? 'password' : 'text');
      const icon = this.querySelector('i');
      if (icon) {
        icon.classList.toggle('fa-eye');
        icon.classList.toggle('fa-eye-slash');
      }
    });
  }

  const box = document.querySelector('.auth-container');
  if (box) {
    box.style.opacity = 0;
    box.style.transform = 'translateY(30px)';
    setTimeout(() => {
      box.style.transition = 'all .6s ease';
      box.style.opacity = 1;
      box.style.transform = 'translateY(0)';
    }, 100);
  }
});
})();
