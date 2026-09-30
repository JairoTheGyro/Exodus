import Storage from './storage.js';
import { applyTemplePresentation } from './temple.js';

const saved = Storage.getJSON('odysseus-theme', null);
applyTemplePresentation(saved?.colors?.presentation === 'temple');
