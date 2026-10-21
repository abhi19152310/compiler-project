/* Guidance stays in its own panel. No editor mutations occur without a click. */
(() => {
  const panel = document.querySelector('#writing-assistant');
  if (!panel) return;
  const catalog = JSON.parse(document.querySelector('#assistant-catalog').textContent);
  const editors = [...document.querySelectorAll('#source, #followup-source')];
  const status = panel.querySelector('#assistant-status');
  const current = panel.querySelector('#assistant-current-text');
  const suggestions = panel.querySelector('#assistant-suggestions');
  const fields = panel.querySelector('#assistant-fields');
  const builderResult = panel.querySelector('#assistant-builder-result');
  const builderText = panel.querySelector('#assistant-builder-text');
  const builderNote = panel.querySelector('#assistant-builder-note');
  const insertButton = panel.querySelector('#assistant-insert');
  let editor = editors[0];
  let selectedTemplate = null;
  let choices = [];
  let timer;
  let controller;
  let sequence = 0;
  let latest = null;
  let composing = false;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function readValues() {
    return Object.fromEntries([...fields.querySelectorAll('[data-assistant-field]')].map(input => [input.dataset.assistantField, input.value]));
  }

  function populateTargets(select, previous) {
    select.replaceChildren();
    const eligible = choices.filter(choice => !(selectedTemplate?.id === 'rounded' && choice.type === 'page') && !(selectedTemplate?.id === 'text-color' && choice.type === 'image'));
    const placeholder = node('option', eligible.length ? 'Choose a component' : 'Create a component first');
    placeholder.value = '';
    select.append(placeholder);
    for (const choice of eligible) {
      const option = node('option', choice.label);
      option.value = choice.value;
      select.append(option);
    }
    if (eligible.some(choice => choice.value === previous)) select.value = previous;
    else if (eligible.length === 1) select.value = eligible[0].value;
  }

  function showFields(template) {
    fields.replaceChildren();
    for (const spec of template.fields) {
      const label = node('label', spec.label);
      const id = `assistant-field-${spec.key}`;
      label.htmlFor = id;
      const input = document.createElement(spec.options !== null ? 'select' : 'input');
      input.id = id;
      input.dataset.assistantField = spec.key;
      if (spec.key === 'target') {
        populateTargets(input, spec.default);
      } else if (spec.options !== null) {
        for (const value of spec.options) {
          const option = node('option', value);
          option.value = value;
          input.append(option);
        }
        if (spec.key === 'color') {
          const option = node('option', 'Custom hex color');
          option.value = 'custom';
          input.append(option);
        }
        input.value = spec.default;
      } else {
        input.type = 'text';
        input.value = spec.default;
        if (spec.key === 'src') input.placeholder = 'https://example.com/photo.jpg or logo.png';
      }
      input.addEventListener('input', schedule);
      if (spec.options !== null) input.addEventListener('change', () => {
        if (spec.key === 'color') {
          const custom = fields.querySelector('#assistant-custom-color');
          custom.hidden = input.value !== 'custom';
        }
        schedule();
      });
      fields.append(label, input);
      if (spec.key === 'color') {
        const wrapper = node('div');
        wrapper.id = 'assistant-custom-color';
        wrapper.hidden = true;
        const customLabel = node('label', 'Six-digit hex color');
        customLabel.htmlFor = 'assistant-hex';
        const custom = document.createElement('input');
        custom.type = 'text';
        custom.id = 'assistant-hex';
        custom.value = '#ffff00';
        custom.placeholder = '#ffff00';
        custom.addEventListener('input', schedule);
        wrapper.append(customLabel, custom);
        fields.append(wrapper);
      }
    }
  }

  function snapshot() {
    const values = readValues();
    if (values.color === 'custom') values.color = fields.querySelector('#assistant-hex').value;
    return {source: editor.value, cursor: editor.selectionStart, mode: editor.id === 'followup-source' ? 'update' : 'new',
      template: selectedTemplate?.id || null, values};
  }

  function validSnapshot(saved) {
    return saved && saved.editor === editor && saved.request.source === editor.value && saved.request.cursor === editor.selectionStart;
  }

  function apply(item, saved) {
    if (!validSnapshot(saved) || !item.ready) {
      schedule();
      return;
    }
    if (item.action === 'insert') {
      const separator = editor.value && !editor.value.endsWith('\n') ? '\n' : '';
      const value = separator + item.text;
      editor.setRangeText(value, editor.value.length, editor.value.length, 'end');
    } else {
      editor.setRangeText(item.replacement || item.text, saved.data.span.start, saved.data.span.end, 'end');
    }
    editor.focus();
    editor.dispatchEvent(new Event('input', {bubbles: true}));
  }

  function render(data, saved) {
    choices = data.targets;
    const select = fields.querySelector('[data-assistant-field="target"]');
    if (select) {
      const previous = select.value;
      populateTargets(select, previous);
      if (select.value !== previous) {
        schedule();
        return;
      }
    }
    current.textContent = data.span.text || 'No instruction here yet.';
    status.textContent = data.message;
    status.dataset.status = data.status;
    suggestions.replaceChildren();
    for (const suggestion of data.suggestions) {
      const card = node('div', '', 'assistant-suggestion');
      card.append(node('p', suggestion.label, 'assistant-caption'), node('code', suggestion.text));
      if (suggestion.message) card.append(node('p', suggestion.message, 'assistant-note'));
      const button = node('button', 'Apply suggestion', 'button button-secondary');
      button.type = 'button';
      button.disabled = !suggestion.ready;
      button.addEventListener('click', () => apply(suggestion, saved));
      card.append(button);
      suggestions.append(card);
    }
    builderResult.hidden = !data.builder;
    if (data.builder) {
      builderText.textContent = data.builder.text;
      builderNote.textContent = data.builder.message;
      insertButton.disabled = !data.builder.ready;
      insertButton.textContent = data.builder.action === 'insert' ? 'Insert instruction' : 'Replace instruction';
    }
  }

  async function refresh() {
    if (composing) return;
    const currentSequence = ++sequence;
    controller?.abort();
    controller = new AbortController();
    const saved = {editor, request: snapshot(), data: null};
    panel.querySelector('#assistant-editor').textContent = editor.id === 'followup-source' ? 'Helping with: follow-up instruction' : 'Helping with: page instructions';
    panel.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(panel.dataset.endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(saved.request), signal: controller.signal});
      const data = await response.json();
      if (currentSequence !== sequence || !validSnapshot(saved)) return;
      if (!response.ok) throw new Error(data.error || 'Suggestions are temporarily unavailable.');
      saved.data = data;
      latest = saved;
      render(data, saved);
    } catch (error) {
      if (error.name !== 'AbortError' && currentSequence === sequence) {
        latest = null;
        suggestions.replaceChildren();
        builderResult.hidden = true;
        status.textContent = error.message || 'Suggestions are temporarily unavailable. You can keep editing.';
      }
    } finally {
      if (currentSequence === sequence) panel.setAttribute('aria-busy', 'false');
    }
  }

  function schedule() {
    clearTimeout(timer);
    controller?.abort();
    sequence++;
    latest = null;
    insertButton.disabled = true;
    suggestions.querySelectorAll('button').forEach(button => { button.disabled = true; });
    timer = setTimeout(refresh, 250);
  }

  for (const input of editors) {
    for (const event of ['input', 'click', 'keyup', 'select', 'focus']) {
      input.addEventListener(event, () => { editor = input; schedule(); });
    }
    input.addEventListener('compositionstart', () => { composing = true; });
    input.addEventListener('compositionend', () => { composing = false; schedule(); });
  }
  panel.querySelectorAll('[data-assistant-template]').forEach(button => {
    button.addEventListener('click', () => {
      selectedTemplate = catalog.find(template => template.id === button.dataset.assistantTemplate);
      panel.querySelectorAll('[data-assistant-template]').forEach(action => action.setAttribute('aria-pressed', String(action === button)));
      showFields(selectedTemplate);
      schedule();
    });
  });
  insertButton.addEventListener('click', () => { if (latest) apply(latest.data.builder, latest); });
  document.querySelector('#load-sample').addEventListener('click', () => { editor = editors[0]; schedule(); });
  refresh();
})();
