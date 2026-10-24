// Starts translations on a page (index.html and login.html load this), and
// wires a language menu if the page has one (the sign-in page does).
import { LANGUAGE_EVENT, currentLanguage, fillLanguageSelect, setLanguage, startTranslations } from './i18n.js';


function wireLoginMenu() {
  const select = document.getElementById('login-language');
  if (!select || select.dataset.bound) return;
  select.dataset.bound = '1';
  fillLanguageSelect(select);
  // Before sign-in the choice is kept in this browser only.
  select.addEventListener('change', () => setLanguage(select.value, { saveToAccount: false }));
  document.addEventListener(LANGUAGE_EVENT, () => { select.value = currentLanguage(); });
}

startTranslations();
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wireLoginMenu, { once: true });
else wireLoginMenu();
