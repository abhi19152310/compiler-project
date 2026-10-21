const source = document.querySelector('#source');
const lineNumbers = document.querySelector('#line-numbers');
const lineCount = document.querySelector('#line-count');
const dirtyNote = document.querySelector('#dirty-note');
const initialSource = source.value;
const compileButton = document.querySelector('#compile-button');

function updateEditor() {
  const lines = source.value.split('\n').length;
  lineNumbers.textContent = Array.from({length: lines}, (_, index) => index + 1).join('\n');
  lineCount.textContent = `${lines} ${lines === 1 ? 'line' : 'lines'}`;
  dirtyNote.hidden = source.value === initialSource;
  lineNumbers.scrollTop = source.scrollTop;
}
source.addEventListener('input', updateEditor);
source.addEventListener('scroll', () => { lineNumbers.scrollTop = source.scrollTop; });
updateEditor();

document.querySelector('#load-sample').addEventListener('click', () => {
  source.value = document.querySelector('#sample-source').content.textContent;
  source.scrollTop = 0;
  updateEditor();
  source.focus();
});
document.querySelector('.guide-link').addEventListener('click', () => {
  document.querySelector('#sentence-guide').open = true;
});

// Without JavaScript, panels remain readable. Enhance them into keyboard tabs.
for (const group of document.querySelectorAll('[data-tab-group]')) {
  const tabs = Array.from(group.querySelectorAll('[data-tab]'));
  function activate(selected, moveFocus = false) {
    for (const tab of tabs) {
      const active = tab === selected;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      document.getElementById(tab.dataset.tab).hidden = !active;
    }
    if (moveFocus) selected.focus();
  }
  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener('click', () => activate(tab));
    tab.addEventListener('keydown', event => {
      let target;
      if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
      if (event.key === 'ArrowLeft') target = tabs[(index - 1 + tabs.length) % tabs.length];
      if (event.key === 'Home') target = tabs[0];
      if (event.key === 'End') target = tabs[tabs.length - 1];
      if (target) { event.preventDefault(); activate(target, true); }
    });
  }
  activate(tabs[0]);
}
source.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault();
    if (!compileButton.disabled) document.querySelector('#compile-form').requestSubmit();
  }
});
document.querySelector('#compile-form').addEventListener('submit', () => {
  compileButton.disabled = true;
  compileButton.querySelector('span').textContent = 'Compiling...';
});
window.addEventListener('pageshow', () => {
  compileButton.disabled = false;
  compileButton.querySelector('span').textContent = 'Compile Webpage';
});
for (const button of document.querySelectorAll('[data-source-line]')) {
  button.addEventListener('click', () => {
    const line = Number(button.dataset.sourceLine);
    const targetEditor = document.querySelector('#' + (button.dataset.sourceEditor || 'source')) || source;
    const lines = targetEditor.value.split('\n');
    const start = lines.slice(0, line - 1).reduce((length, text) => length + text.length + 1, 0);
    targetEditor.focus();
    targetEditor.setSelectionRange(start, start + (lines[line - 1] || '').length);
    targetEditor.scrollTop = Math.max(0, (line - 3) * parseFloat(getComputedStyle(targetEditor).lineHeight));
    targetEditor.scrollLeft = 0;
    if (targetEditor === source) lineNumbers.scrollTop = source.scrollTop;
  });
}
