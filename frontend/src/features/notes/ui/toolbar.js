/** Panel search, archive and list/grid controls. */
export function createToolbar({
  app,
  state,
  persistence,
  api,
  showToast,
  _renderNotes,
  _fetchNotes,
  _applyMasonry
}) {
  let _searchTimer = null;
  function cancelPendingSearch() {
    clearTimeout(_searchTimer);
    _searchTimer = null;
  }

  function wireExportImport(pane) {
    const exportBtn = pane.querySelector('#notes-export-toggle');
    const exportOptions = pane.querySelector('#notes-export-options');
    if (!exportBtn || !exportOptions) return;
    const closeExport = () => {
      exportOptions.hidden = true;
      exportBtn.setAttribute('aria-expanded', 'false');
    };
    exportBtn.addEventListener('click', () => {
      exportOptions.hidden = !exportOptions.hidden;
      exportBtn.setAttribute('aria-expanded', String(!exportOptions.hidden));
    });
    exportOptions.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        closeExport();
        exportBtn.focus();
      }
    });
    // Native attachment downloads stream to the browser without a JS Blob or reload.
    exportOptions.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
      closeExport();
      exportBtn.focus();
    }));

    const importBtn = pane.querySelector('#notes-import-select');
    const importFile = pane.querySelector('#notes-import-file');
    const importStatus = pane.querySelector('#notes-import-status');
    if (!importBtn || !importFile || !importStatus) return;
    importBtn.addEventListener('click', () => importFile.click());
    importFile.addEventListener('change', async () => {
      const file = importFile.files?.[0];
      if (!file || importBtn.disabled) return;
      importBtn.disabled = true;
      importStatus.textContent = 'Importing notes…';
      try {
        if (file.size > 10 * 1024 * 1024) throw new Error('Choose a JSON backup no larger than 10 MiB.');
        const response = await api.importJson(file);
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Notes were not imported. Check the backup and try again.');
        const summary = `Imported ${result.imported} note${result.imported === 1 ? '' : 's'} as new copies${result.archived ? ` (${result.archived} archived)` : ''}.`;
        importStatus.textContent = [summary, ...(result.warnings || []).map(w => `${w.message} (${w.count})`)].join(' ');
        await _fetchNotes();
        // Keep an open unsaved note editor intact while refreshing the backing list.
        if (state.open && !pane.querySelector('.note-form')) _renderNotes();
        showToast(summary);
      } catch (error) {
        importStatus.textContent = error.message || 'Notes were not imported.';
      } finally {
        importBtn.disabled = false;
        importFile.value = '';
      }
    });
  }

  function wireToolbar(pane) {
    wireExportImport(pane);

    // Search: filter the complete loaded list locally after a short pause;
    // clearing applies immediately and never waits or fetches.
    const searchEl = document.getElementById('notes-search');
    if (searchEl) {
      searchEl.addEventListener('input', () => {
        cancelPendingSearch();
        const query = searchEl.value.trim().toLowerCase();
        const applySearch = () => {
          _searchTimer = null;
          app.setSearchQuery(query);
          _renderNotes();
        };
        if (!query) applySearch();
        else _searchTimer = setTimeout(applySearch, 250);
      });
    }

    // View toggle
    const archiveBtn = document.getElementById('notes-archive-toggle');
    if (archiveBtn) {
      const ARCHIVE_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 002 2h12a2 2 0 002-2V8"/><path d="M10 12h4"/></svg><span class="notes-header-btn-label">Archive</span>';
      const CLOSE_ICON   = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg><span class="notes-header-btn-label">Archive</span>';
      const syncArchiveBtn = () => {
        archiveBtn.classList.toggle('active', state.showingArchived);
        archiveBtn.title = state.showingArchived ? 'Exit archive' : 'View archive';
        archiveBtn.style.opacity = state.showingArchived ? '1' : '0.8';
        // Swap to an X while in archive view so it doubles as a close-back-
        // to-active-notes toggle.
        archiveBtn.innerHTML = state.showingArchived ? CLOSE_ICON : ARCHIVE_ICON;
        // Tint the whole pane so it's obvious you're not in the active list.
        pane.classList.toggle('notes-pane-archive', state.showingArchived);
      };
      syncArchiveBtn();
      archiveBtn.addEventListener('click', async () => {
        app.setShowingArchived(!state.showingArchived);
        // Label and reminder filters belong to one view; start the other view unfiltered.
        app.setActiveLabel(null);
        app.setActiveFilter(null);
        app.clearSelection();
        syncArchiveBtn();
        // Brief fade so the body content swap doesn't snap : the bg-tint
        // change is already eased by CSS transitions on .notes-pane*.
        const _bodyEl = document.querySelector('#notes-pane .notes-pane-body');
        if (_bodyEl) {
          _bodyEl.style.transition = 'opacity 0.18s ease';
          _bodyEl.style.opacity = '0.25';
        }
        await _fetchNotes();
        _renderNotes();
        if (_bodyEl) {
          requestAnimationFrame(() => {
            _bodyEl.style.opacity = '';
            _bodyEl.addEventListener('transitionend', () => { _bodyEl.style.transition = ''; }, { once: true });
          });
        }
      });
    }
    const viewBtn = document.getElementById('notes-view-toggle');
    if (viewBtn) {
      pane.classList.toggle('notes-view-grid', state.viewMode === 'grid');
      // Label shows what you'll switch TO : "Grid" while in list, "List" while in grid.
      const _setViewLabel = () => {
        const lbl = viewBtn.querySelector('.notes-header-btn-label');
        if (lbl) lbl.textContent = state.viewMode === 'grid' ? 'List' : 'Grid';
      };
      _setViewLabel();
      requestAnimationFrame(() => _applyMasonry(document.querySelector('#notes-pane .notes-pane-body')));
      viewBtn.addEventListener('click', () => {
        app.setViewMode(state.viewMode === 'grid' ? 'list' : 'grid');
        try { persistence.setItem('odysseus-notes-view', state.viewMode); } catch {}
        pane.classList.toggle('notes-view-grid', state.viewMode === 'grid');
        _setViewLabel();
        requestAnimationFrame(() => _applyMasonry(document.querySelector('#notes-pane .notes-pane-body')));
      });
    }

  }
  return { wireToolbar, cancelPendingSearch };
}
