(function () {
  if (window.__BARCODE_INIT__) return;
  window.__BARCODE_INIT__ = true;

  const input = document.getElementById('barcode');
  const help = document.getElementById('barcodeHelp');
  if (!input) return;

  input.setAttribute('dir', 'ltr');
  input.setAttribute('inputmode', 'numeric');
  input.setAttribute('autocomplete', 'off');

  const endpoint = input.getAttribute('data-validate-url')
    || input.getAttribute('data-barcode-url')
    || '/api/barcode/validate';

  const getCSRFToken = window.getCSRFToken || (() =>
    document.querySelector('meta[name="csrf-token"]')?.content ||
    document.querySelector('input[name="csrf_token"]')?.value || '');

  const toLatinDigits = (str) =>
    str.replace(/[\u0660-\u0669\u06F0-\u06F9]/g, (ch) =>
      String.fromCharCode((ch.charCodeAt(0) - (/[٠-٩]/.test(ch) ? 0x0660 : 0x06F0)) + 48)
    );

  const extractDigits = (str) => toLatinDigits(str).replace(/\D+/g, '');

  const ean13CheckDigit = (code12) => {
    let sum = 0;
    for (let i = 0; i < 12; i++) {
      sum += (i % 2 === 0 ? 1 : 3) * parseInt(code12[i]);
    }
    const remainder = sum % 10;
    return remainder === 0 ? 0 : 10 - remainder;
  };

  const isValidEAN13 = (code) =>
    code.length === 13 && ean13CheckDigit(code.slice(0, 12)) === parseInt(code[12]);

  const setState = (className, message) => {
    input.classList.remove('is-valid', 'is-invalid');
    if (className) input.classList.add(className);
    if (help) help.textContent = message || '';
  };

  let timer = null;
  let controller = null;
  let lastChecked = '';

  const validate = () => {
    let value = extractDigits(input.value);
    if (value.length > 13) value = value.slice(0, 13);
    input.value = value;

    input.classList.remove('is-valid', 'is-invalid');

    if (!value || value.length < 12) {
      setState('', '');
      return;
    }

    if (timer) clearTimeout(timer);
    timer = setTimeout(() => runValidation(value), 300);
  };

  const runValidation = async (code) => {
    lastChecked = code;
    setState('', 'جارٍ التحقق...');

    if (controller) controller.abort();
    controller = new AbortController();

    try {
      const res = await fetch(`${endpoint}?code=${encodeURIComponent(code)}`, {
        method: 'GET',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': getCSRFToken()
        },
        signal: controller.signal,
        credentials: 'same-origin'
      });

      const data = await res.json();

      if (lastChecked !== extractDigits(input.value)) return;

      if (data.normalized && data.normalized !== input.value) {
        input.value = extractDigits(data.normalized);
      }

      const finalValue = input.value;

      if (data.valid === false) {
        setState('is-invalid', 'باركود غير صالح');
      } else if (data.exists) {
        setState('is-invalid', 'الباركود مستخدم بالفعل');
      } else if (finalValue.length === 13 && !isValidEAN13(finalValue)) {
        setState('is-invalid', 'باركود غير صالح (فحص EAN-13)');
      } else {
        setState('is-valid', 'الباركود صالح');
      }
    } catch (e) {
      if (e.name === 'AbortError') return;

      if (input.value.length === 13 && isValidEAN13(input.value)) {
        setState('is-valid', '');
      } else {
        setState('', 'تعذر التحقق الآن، سيتم الفحص عند الحفظ');
      }
    }
  };

  input.addEventListener('input', validate);
  input.addEventListener('paste', () => setTimeout(validate, 0));

  input.addEventListener('blur', () => {
    const value = extractDigits(input.value);
    if (value && value.length < 12) {
      setState('is-invalid', 'الباركود قصير');
    }
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const form = input.closest('form');
      if (!form) return;
      const fields = Array.from(form.querySelectorAll('input, select, textarea, button'))
        .filter(el => !el.disabled && el.offsetParent !== null);
      const index = fields.indexOf(input);
      if (index > -1 && fields[index + 1]) {
        fields[index + 1].focus();
      }
    }
  });
})();
