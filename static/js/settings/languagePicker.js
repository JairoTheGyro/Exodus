// Settings → Appearance → Language: saved with the person's account.
import { LANGUAGE_EVENT, currentLanguage, fillLanguageSelect, setLanguage } from '../i18n.js';

export function mountLanguagePicker(select) {
  if (!select) return;
  fillLanguageSelect(select);
  if (select.dataset.bound) return;
  select.dataset.bound = '1';
  select.addEventListener('change', () => setLanguage(select.value));
  document.addEventListener(LANGUAGE_EVENT, () => { select.value = currentLanguage(); });
}
