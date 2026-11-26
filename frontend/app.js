(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const phaseLabels = {
    positions: 'Раунд 1. Позиции',
    negotiation: 'Раунд 2. Переговоры',
    amendments: 'Раунд 3. Поправки',
    preparing_protocol: 'Подготовка протокола',
    forecasting: 'Расчёт прогноза',
    voting: 'Голосование',
    calculating_result: 'Расчёт последствий',
  };
  const voteLabels = { for: 'За', against: 'Против', abstain: 'Воздержался' };
  const formatNumber = new Intl.NumberFormat('ru-RU');
  const savedGame = 'city_n_game_id';
  const draftKey = (id) => `city_n_draft_${id}`;
  const createKey = 'city_n_create_key';
  const readableValue = (value) => typeof value === 'number' ? formatNumber.format(value) : value;

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function indexLabel(index) {
    return String(index + 1).padStart(2, '0');
  }

  function requestKey() {
    return Array.from(crypto.getRandomValues(new Uint8Array(16)), (part) => part.toString(16).padStart(2, '0')).join('');
  }

  async function api(path = '', method = 'GET', body, key) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method === 'POST') headers['Idempotency-Key'] = key || requestKey();
    const url = `/api/v1/games${path}`;
    const options = { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store' };
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      if (method === 'GET') throw error;
      response = await fetch(url, options);
    }
    const payload = await response.json().catch(() => null);
    if (response.ok && payload !== null) return payload;
    throw Object.assign(new Error(payload?.message || 'Запрос не выполнен.'), payload, { status: response.status });
  }

  class GameApp {
    constructor() {
      this.game = null;
      this.draft = null;
      this.cursor = 0;
      this.messages = new Map();
      this.rounds = new Map();
      this.analysisResults = new Map();
      this.pollTimer = null;
      this.pollRefresh = false;
      this.busy = false;
      this.inputId = null;

      window.addEventListener('hashchange', () => this.route());
      document.querySelector('.skip-link').onclick = (event) => {
        event.preventDefault();
        $('main').focus();
      };
      $('role-settings').onsubmit = (event) => {
        event.preventDefault();
        void this.act(() => this.start());
      };
      $('automatic-settings').onclick = () => this.fillDefaults();
      $('next-role').onclick = () => {
        const index = this.roles.findIndex((role) => role.id === this.selectedRole);
        this.selectRole(this.roles[index + 1].id);
        this.saveDraft();
        $('questionnaire-title').focus();
      };
      $('manual-input').onsubmit = (event) => {
        event.preventDefault();
        const pending = this.game?.pending_input;
        if (!pending || pending.input_id !== this.inputId) return;
        const data = new FormData(event.currentTarget);
        const value = pending.type === 'speech' ? { type: 'speech', content: data.get('content') }
          : { type: 'vote', vote: data.get('vote') };
        void this.act(() => this.command(`/inputs/${pending.input_id}`, value));
      };
      $('pause-btn').onclick = () => this.act(() => this.command(this.game.pause_state === 'none' ? '/pause' : '/continue'));
      $('stop-btn').onclick = () => this.act(() => this.command('/cancel'));
      $('retry-result').onclick = () => this.act(() => this.command('/retry-result'));
      $('instruction-form').onsubmit = (event) => {
        event.preventDefault();
        const input = $('instruction-text');
        void this.act(async () => {
          await api(`/${this.game.game_id}/roles/${$('instruction-role').value}/instructions`, 'POST', { content: input.value });
          input.value = '';
        });
      };
      $('analysis-form').onsubmit = (event) => {
        event.preventDefault();
        void this.requestAnalysis();
      };
      $('analysis-role').onchange = () => this.showAnalysis();
      $('finish-game').onclick = () => {
        this.clear();
        this.navigate('start');
      };
      void this.restore();
    }

    get roles() {
      return this.game.scenario.roles;
    }

    roleName(id) {
      return this.roles.find((role) => role.id === id)?.name || id;
    }

    notice(id, message = '') {
      const notice = $(id);
      if (notice.textContent !== message) notice.textContent = message;
      notice.hidden = !message;
    }

    async act(callback) {
      if (this.busy) return;
      this.busy = true;
      this.lockSettings(true);
      this.notice('game-error');
      try {
        await callback();
      } catch (error) {
        this.handleError(error);
      } finally {
        this.busy = false;
        this.lockSettings(false);
      }
    }

    lockSettings(locked) {
      for (const id of ['submit-settings-btn', 'automatic-settings', 'next-role']) $(id).disabled = locked;
      $('roles-nav').inert = locked;
      $('role-settings').inert = locked;
    }

    handleError(error) {
      if (error.status === 404 && error.code !== 'ROLE_NOT_FOUND') {
        this.clear();
        this.navigate('start');
        this.notice('game-error', 'Партия недоступна. Начните новую игру.');
      } else {
        this.notice('game-error', error.message || 'Не удалось связаться с сервером.');
      }
    }

    clear() {
      clearTimeout(this.pollTimer);
      const id = this.game?.game_id || localStorage.getItem(savedGame);
      if (id) localStorage.removeItem(draftKey(id));
      localStorage.removeItem(savedGame);
      this.game = this.draft = this.inputId = null;
      this.pollRefresh = false;
      this.cursor = 0;
      this.messages.clear();
      this.rounds.clear();
      this.analysisResults.clear();
      this.analysisRequest = null;
      this.analysisError = null;
      $('analysis-role').replaceChildren();
      $('analysis-result').replaceChildren();
      $('instruction-role').replaceChildren();
      $('instruction-text').value = '';
      $('debate-feed').replaceChildren();
      $('journal-archive').open = false;
      $('final-protocol').open = false;
      $('live-journal').prepend($('journal-content'));
      this.notice('game-error');
    }

    async restore() {
      const gameId = localStorage.getItem(savedGame);
      if (gameId) {
        try {
          this.apply(await api(`/${gameId}`), true);
        } catch (error) {
          this.handleError(error);
        }
      } else {
        this.route();
      }
    }

    route() {
      const location = window.location.hash.slice(1);
      if (location === 'instruction' || location === 'start') {
        this.screen(location);
      } else if (this.game) {
        this.navigate(this.gameScreen());
      } else if (location === 'settings') {
        void this.act(async () => {
          const key = sessionStorage.getItem(createKey) || requestKey();
          sessionStorage.setItem(createKey, key);
          const snapshot = await api('', 'POST', undefined, key);
          sessionStorage.removeItem(createKey);
          this.apply(snapshot, true);
        });
      } else {
        this.screen('start');
      }
    }

    gameScreen() {
      return this.game.status === 'draft' ? 'settings' : this.game.status === 'running' ? 'debate' : 'final';
    }

    navigate(name) {
      if (window.location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
      this.screen(name);
    }

    screen(name) {
      const previous = this.currentScreen;
      this.currentScreen = name;
      for (const view of document.querySelectorAll('.screen-view')) view.hidden = view.dataset.screenView !== name;
      for (const stage of document.querySelectorAll('[data-stage]')) {
        if (stage.dataset.stage === name) stage.setAttribute('aria-current', 'step');
        else stage.removeAttribute('aria-current');
      }
      if (name !== 'instruction') document.querySelector('video').pause();
      if (name === 'start') {
        const destination = this.game ? this.gameScreen() : 'settings';
        const link = $('start-link');
        link.href = `#${destination}`;
        const labels = { settings: 'Настроить агентов', debate: 'Вернуться к переговорам', final: 'Посмотреть итоги' };
        link.firstChild.textContent = `${labels[destination]} `;
      }
      if (previous !== name) {
        window.scrollTo(0, 0);
        if (previous) {
          const heading = document.querySelector(`[data-screen-view="${name}"] h1`);
          heading.tabIndex = -1;
          heading.focus({ preventScroll: true });
        }
      }
    }

    apply(snapshot, recover = false) {
      if (!recover && this.game?.game_id !== snapshot.game_id) return;
      if (!recover && snapshot.last_event_id < this.game.last_event_id) return;
      const previous = this.game;
      this.game = snapshot;
      localStorage.setItem(savedGame, snapshot.game_id);
      if (recover) this.cursor = snapshot.last_event_id;
      for (const message of snapshot.messages) this.append(message);

      if (snapshot.status === 'draft' && (!previous || !this.draft)) this.initSettings();
      if (snapshot.status === 'running') this.renderDebate();
      if (['completed', 'cancelled', 'failed'].includes(snapshot.status)) this.renderResult();
      const location = window.location.hash;
      if (location !== '#instruction' && (recover || location !== '#start')) this.navigate(this.gameScreen());
      if (recover && snapshot.status === 'running') this.schedulePoll();
    }

    initSettings() {
      const settings = this.game.settings;
      this.questionnaires = this.game.scenario.questionnaires;
      const stored = localStorage.getItem(draftKey(this.game.game_id));
      let savedDraft;
      try { savedDraft = JSON.parse(stored); } catch (_) { savedDraft = null; }
      $('automatic-settings').hidden = !this.questionnaires;
      if (this.questionnaires) {
        const automatic = settings.setup_mode === 'automatic';
        this.draft = savedDraft?.answers ? savedDraft : {
          mode: automatic ? 'automatic' : 'manual',
          usedDefaults: automatic,
          answers: Object.fromEntries(this.roles.map(({ id }) => [
            id, settings.roles.find((role) => role.role_id === id)?.answers || {},
          ])),
        };
      } else {
        // A draft stored by an older server may still describe the original settings schema.
        this.draft = Array.isArray(savedDraft) ? savedDraft : settings.roles.map(({ spent_on_conditions_rub, ...role }) => role);
      }
      const selected = this.roles.find(({ id }) => this.draft.selectedRole === id);
      this.selectRole(selected?.id || this.roles[0].id);
    }

    saveDraft() {
      localStorage.setItem(draftKey(this.game.game_id), JSON.stringify(this.draft));
    }

    fillDefaults() {
      this.draft = {
        mode: 'automatic',
        usedDefaults: true,
        selectedRole: this.selectedRole,
        answers: Object.fromEntries(this.roles.map(({ id }) => [id, { ...this.questionnaires[id].defaults }])),
      };
      this.saveDraft();
      this.selectRole(this.selectedRole);
    }

    missingQuestion(roleId) {
      const answers = this.draft.answers[roleId];
      return this.questionnaires[roleId].fields.find((field) => field.required
        && !field.options.some((option) => Object.is(option.value, answers[field.id])));
    }

    selectRole(roleId) {
      this.selectedRole = roleId;
      if (this.questionnaires) this.draft.selectedRole = roleId;
      this.notice('settings-error');
      const form = $('role-settings');
      const role = this.roles.find(({ id }) => id === roleId);
      const heading = element('h2', role.name, 'questionnaire-title');
      heading.id = 'questionnaire-title';
      heading.tabIndex = -1;
      const header = element('header', null, 'questionnaire-heading');
      header.append(heading);
      if (role.interest) header.append(element('p', role.interest));
      form.replaceChildren(header);
      if (this.questionnaires) this.renderQuestions(form, roleId);
      else this.renderLegacySettings(form, roleId);
      this.renderSettingsNav();
    }

    renderSettingsNav() {
      const nav = $('roles-nav');
      if (!nav.children.length || nav.firstChild.dataset.game !== this.game.game_id) {
        nav.replaceChildren();
        for (const [index, role] of this.roles.entries()) {
          const row = element('li');
          row.dataset.game = this.game.game_id;
          const button = element('button', null, 'role-link');
          const number = element('span', indexLabel(index), 'role-number');
          number.setAttribute('aria-hidden', 'true');
          const mark = element('span', '', 'role-check');
          mark.setAttribute('aria-hidden', 'true');
          const indicator = element('span', '', 'sr-only');
          button.append(number, element('span', role.name), mark, indicator);
          button.type = 'button';
          button.onclick = () => {
            this.selectRole(role.id);
            this.saveDraft();
          };
          row.append(button);
          nav.append(row);
        }
      }
      let completed = 0;
      for (const [index, role] of this.roles.entries()) {
        const button = nav.children[index].firstChild;
        if (this.selectedRole === role.id) button.setAttribute('aria-current', 'true');
        else button.removeAttribute('aria-current');
        const complete = this.questionnaires && !this.missingQuestion(role.id);
        if (complete) completed++;
        button.querySelector('.role-check').textContent = complete ? '✓' : '';
        button.lastChild.textContent = complete ? ', анкета заполнена' : '';
      }
      if (this.questionnaires) {
        const progress = $('settings-progress');
        const count = `${completed} / ${this.roles.length}`;
        if (progress.textContent !== count) progress.textContent = count;
        progress.setAttribute('aria-label', `Анкет заполнено: ${completed} из ${this.roles.length}`);
      } else {
        $('settings-progress').textContent = '';
      }
      const message = this.draft.mode === 'automatic' ? 'Все ответы заполнены автоматически. Проверьте их и запустите партию.'
        : this.draft.usedDefaults ? 'Автоматические ответы отредактированы. Партия запустится с ручными настройками.' : '';
      this.notice('setup-mode', message);
      $('next-role').hidden = this.selectedRole === this.roles.at(-1).id;
    }

    renderQuestions(form, roleId) {
      const answers = this.draft.answers[roleId];
      for (const question of this.questionnaires[roleId].fields) {
        const value = answers[question.id];
        let input;
        let read;
        if (question.options.length) {
          const options = question.options;
          const selected = options.findIndex((option) => Object.is(option.value, value));
          input = this.select([['', 'Выберите ответ'], ...options.map((option, index) => [index, option.label])],
            selected === -1 ? '' : selected);
          read = () => input.value === '' ? undefined : options[Number(input.value)].value;
        } else {
          input = Object.assign(element('textarea'), { value: value ?? '', rows: 3, maxLength: 6000 });
          input.placeholder = 'Ваши аргументы или условия';
          read = () => input.value;
        }
        input.required = question.required;
        this.settingField(form, question.label, question.id, input, () => {
          const answer = read();
          if (answer === undefined) delete answers[question.id];
          else answers[question.id] = answer;
          this.draft.mode = 'manual';
          this.renderSettingsNav();
        }, question.hint);
      }
    }

    renderLegacySettings(form, roleId) {
      const draft = this.draft.find((role) => role.role_id === roleId);
      const schema = this.game.scenario.role_settings_schema[roleId];
      const mode = this.select([['ai', 'ИИ'], ['human', 'Я сам']], draft.control_mode);
      this.settingField(form, 'Управление ролью', 'control_mode', mode, (input) => draft.control_mode = input.value);
      const money = Object.assign(element('input'), {
        type: 'number', min: 0, max: schema.pledged_rub_max, step: 1, required: true, value: draft.pledged_rub,
      });
      this.settingField(form, 'Взнос, ₽', 'pledged_rub', money, (input) => draft.pledged_rub = input.value === '' ? null : input.valueAsNumber);
      for (const condition of schema.conditions) {
        const value = draft.conditions[condition.id];
        let field;
        if (condition.allowed) field = this.select(condition.allowed.map((option) => [option, option]), value);
        else if (condition.type === 'boolean') field = Object.assign(element('input'), { type: 'checkbox', checked: value });
        else field = Object.assign(element('input'), {
          type: condition.type === 'integer' ? 'number' : 'text', value, required: true,
          ...(condition.min_value == null ? {} : { min: condition.min_value }),
          ...(condition.max_value == null ? {} : { max: condition.max_value }),
        });
        this.settingField(form, condition.label, `conditions.${condition.id}`, field, (input) => {
          draft.conditions[condition.id] = condition.type === 'boolean' ? input.checked
            : condition.type === 'integer' ? (input.value === '' ? null : Number(input.value)) : input.value;
        });
      }
      const strategy = Object.assign(element('textarea'), { value: draft.strategy || '', maxLength: 6000, rows: 3 });
      this.settingField(form, 'Стратегия', 'strategy', strategy, (input) => draft.strategy = input.value.trim() || null);
    }

    settingField(form, text, path, field, update, hint) {
      const wrapper = element('div', null, 'question');
      const label = element('label', text);
      field.id = `question-${path}`;
      field.dataset.path = path;
      label.htmlFor = field.id;
      wrapper.append(label);
      const description = element('p', hint, 'question-hint');
      if (hint) wrapper.append(description);
      wrapper.append(field);

      // Native selects can clip long chosen options on narrow screens.
      const chosen = field.nodeName === 'SELECT' ? element('p', '', 'chosen-option') : null;
      if (chosen) wrapper.append(chosen);
      const showChosen = () => {
        if (!chosen) return;
        const option = field.value ? field.selectedOptions[0] : null;
        chosen.textContent = option?.textContent || '';
        chosen.hidden = !option || option.textContent.length < 44;
      };
      showChosen();
      const describedBy = [];
      for (const [suffix, node] of [['hint', hint && description], ['answer', chosen]]) {
        if (!node) continue;
        node.id = `${field.id}-${suffix}`;
        describedBy.push(node.id);
      }
      if (describedBy.length) field.setAttribute('aria-describedby', describedBy.join(' '));
      form.append(wrapper);
      field.oninput = () => {
        field.removeAttribute('aria-invalid');
        this.notice('settings-error');
        update(field);
        showChosen();
        this.saveDraft();
      };
    }

    label(text, field) {
      const label = element('label', text);
      label.append(field);
      return label;
    }

    select(choices, value) {
      const field = element('select');
      for (const [id, label] of choices) field.append(new Option(label, id));
      field.value = value;
      return field;
    }

    settingsError(roleId, path, message) {
      this.selectRole(roleId);
      this.notice('settings-error', message);
      const field = Array.from($('role-settings').elements).find((item) => item.dataset.path === path);
      if (field) field.setAttribute('aria-invalid', 'true');
      // Unlock before focus if a submission routed to a different role.
      this.lockSettings(false);
      (field || $('questionnaire-title')).focus();
    }

    async start() {
      const id = this.game.game_id;
      this.notice('settings-error');
      if (this.questionnaires) {
        for (const { id: roleId } of this.roles) {
          const missing = this.missingQuestion(roleId);
          if (!missing) continue;
          this.settingsError(roleId, missing.id, `Ответьте на обязательные вопросы анкеты «${this.roleName(roleId)}».`);
          return;
        }
      }
      const payload = !this.questionnaires ? { roles: this.draft }
        : this.draft.mode === 'automatic' ? { mode: 'automatic' }
          : { mode: 'manual', answers: this.draft.answers };
      try {
        await api(`/${id}/settings`, 'PUT', payload);
      } catch (error) {
        const issue = error.field_errors?.[0];
        const path = issue?.path || [];
        const answersIndex = path.indexOf('answers');
        const legacyRole = path[0] === 'roles' && this.draft[path[1]]?.role_id;
        const roleId = answersIndex === -1 ? legacyRole : path[answersIndex + 1];
        if (this.roles.some(({ id }) => id === roleId)) {
          const field = path.slice(answersIndex === -1 ? 2 : answersIndex + 2).join('.');
          this.settingsError(roleId, field, issue.message);
          return;
        }
        if (error.status !== 409) throw error;
        const saved = await api(`/${id}`);
        if (saved.status === 'draft') throw error;
        this.apply(saved, true);
        return;
      }
      try {
        await this.command('/start');
      } catch (error) {
        if (!(error instanceof TypeError)) throw error;
        const saved = await api(`/${id}`);
        if (saved.status === 'draft') throw error;
        this.apply(saved, true);
      }
      localStorage.removeItem(draftKey(id));
    }

    async command(path, body) {
      const id = this.game.game_id;
      try {
        const snapshot = await api(`/${id}${path}`, 'POST', body);
        this.apply(snapshot);
      } catch (error) {
        if (error.status === 409) this.apply(await api(`/${id}`));
        throw error;
      } finally {
        if (this.game?.game_id === id && this.game.status === 'running') this.schedulePoll();
      }
    }

    schedulePoll(delay = 650) {
      clearTimeout(this.pollTimer);
      this.pollTimer = setTimeout(() => this.poll(), delay);
    }

    async poll() {
      const id = this.game?.game_id;
      if (!id || this.game.status !== 'running' || this.polling === id) return;
      this.polling = id;
      let delay = 650;
      try {
        const page = await api(`/${id}/events?after=${this.cursor}`);
        if (this.game?.game_id !== id) return;
        for (const event of page.events) {
          if (event.type === 'message.created') this.append(event.payload);
          else this.pollRefresh = true;
        }
        this.cursor = page.next_cursor;
        if (page.has_more) delay = 0;
        else if (this.pollRefresh) {
          const snapshot = await api(`/${id}`);
          if (this.game?.game_id !== id) return;
          this.apply(snapshot);
          this.pollRefresh = false;
        }
      } catch (error) {
        if (this.game?.game_id !== id) return;
        delay = 2000;
        if (error.code === 'EVENT_CURSOR_EXPIRED') {
          try {
            const snapshot = await api(`/${id}`);
            if (this.game?.game_id === id) this.apply(snapshot, true);
          } catch (refreshError) {
            if (this.game?.game_id === id) this.handleError(refreshError);
          }
        } else if (error.status === 404) this.handleError(error);
      } finally {
        if (this.polling === id) this.polling = null;
        if (this.game?.game_id === id && this.game.status === 'running') this.schedulePoll(delay);
      }
    }

    append(message) {
      if (this.messages.has(message.message_id)) return;
      const number = this.messages.size + 1;
      const phase = message.phase;
      let list = this.rounds.get(phase);
      if (!list) {
        const round = element('section', null, 'journal-round');
        round.append(element('h2', phaseLabels[phase] || 'Выступления'));
        list = element('ol', null, 'round-messages');
        list.start = number;
        round.append(list);
        $('debate-feed').append(round);
        this.rounds.set(phase, list);
      }
      const entry = element('li');
      const item = element('article', null, 'speech-item');
      item.tabIndex = -1;
      const meta = element('span', `Реплика ${number}`, 'speech-number');
      item.append(meta, element('h3', this.roleName(message.role_id), 'speech-role'),
        element('p', message.content, 'speech-text'));
      entry.append(item);
      list.append(entry);
      this.messages.set(message.message_id, { item, number });
      this.renderJournalCount();
    }

    renderJournalCount() {
      const count = this.messages.size;
      $('empty-journal').hidden = !!count;
      const limit = this.game.scenario.max_dialogue_messages;
      $('journal-progress').textContent = limit ? `${count} / ${limit} реплик` : `Реплик: ${count}`;
      $('archive-count').textContent = `Реплик: ${count}`;
    }

    renderDebate() {
      const game = this.game;
      const actions = game.available_actions;
      $('live-journal').prepend($('journal-content'));
      this.renderJournalCount();
      const pause = game.pause_state === 'requested' ? ' · Пауза запрошена' : game.pause_state === 'paused' ? ' · Пауза' : '';
      $('phase-title').textContent = (phaseLabels[game.phase] || 'Подготовка участников') + pause;
      $('pause-btn').textContent = game.pause_state === 'none' ? 'Приостановить' : 'Продолжить';
      $('pause-btn').hidden = !actions.includes('pause') && !actions.includes('continue');
      $('stop-btn').hidden = !actions.includes('cancel');

      const agenda = $('hearing-agenda');
      agenda.replaceChildren();
      const phases = Object.keys(phaseLabels);
      for (const [index, phase] of phases.entries()) {
        const item = element('li', phaseLabels[phase]);
        if (phase === game.phase) item.setAttribute('aria-current', 'step');
        if (index < phases.indexOf(game.phase)) item.className = 'phase-passed';
        agenda.append(item);
      }
      this.renderProtocol($('protocol-panel'));
      this.renderVotes($('live-votes'));
      this.renderLegacyInput();
    }

    renderLegacyInput() {
      const game = this.game;
      const actions = game.available_actions;
      const agentSetup = ['manual', 'automatic'].includes(game.settings.setup_mode);
      const aiRoles = game.settings.roles.filter((role) => role.control_mode === 'ai');
      $('instruction-form').hidden = agentSetup || !actions.includes('add_instruction') || !aiRoles.length;
      const roles = $('instruction-role');
      if (roles.options.length !== aiRoles.length) {
        roles.replaceChildren(...aiRoles.map((role) => new Option(this.roleName(role.role_id), role.role_id)));
      }

      const form = $('manual-input');
      const pending = agentSetup ? null : game.pending_input;
      form.hidden = !pending;
      if (this.inputId !== pending?.input_id) {
        form.replaceChildren();
        this.inputId = pending?.input_id;
        if (pending) {
          form.append(element('h2', this.roleName(pending.role_id)));
          if (pending.type === 'speech') {
            const field = Object.assign(element('textarea'), { name: 'content', required: true, maxLength: 6000, rows: 4 });
            form.append(this.label('Ваше выступление', field));
          } else {
            const field = this.select(pending.allowed_votes.map((vote) => [vote, voteLabels[vote]]), '');
            field.name = 'vote';
            field.required = true;
            form.append(this.label(`Ваш голос по протоколу №${pending.protocol_version}`, field));
          }
          form.append(element('button', 'Отправить', 'button button-primary'));
        }
      }
      for (const field of form.elements) field.disabled = !actions.includes('submit_input');
    }

    renderProtocol(container, withTitle = true) {
      const { protocol, forecast } = this.game;
      container.hidden = !protocol;
      container.replaceChildren();
      if (!protocol) return;
      if (withTitle) container.append(element('h2', `Протокол №${protocol.version}`));
      const items = element('dl', null, 'protocol-list');
      for (const item of protocol.items) {
        const value = typeof item.value === 'boolean' ? (item.value ? 'Да' : 'Нет') : readableValue(item.value);
        const group = element('div');
        group.append(element('dt', item.title));
        if (value != null) group.append(element('dd', value));
        if (item.funding.length) {
          const funding = element('dl', null, 'funding-list');
          for (const share of item.funding) {
            const row = element('div');
            row.append(element('dt', this.roleName(share.role_id)),
              element('dd', `${formatNumber.format(share.amount_rub)} ₽`));
            funding.append(row);
          }
          const details = element('dd');
          details.append(funding);
          group.append(details);
        }
        items.append(group);
      }
      container.append(items);
      if (forecast) this.renderIndicators(container, forecast, 'Прогноз при принятии', 'h3');
    }

    renderIndicators(container, projection, title, heading = 'h2') {
      container.append(element(heading, title));
      const list = element('dl', null, 'indicators');
      for (const metric of projection.indicators) {
        const group = element('div');
        group.append(element('dt', metric.label), element('dd', readableValue(metric.final_value)));
        list.append(group);
      }
      container.append(list);
    }

    renderVotes(container) {
      const { vote_summary: summary, protocol_status: status } = this.game;
      container.hidden = !summary;
      container.replaceChildren();
      if (!summary) return;
      container.append(element('h2', 'Голосование'));
      const statusLabel = status === 'accepted' ? 'Протокол принят'
        : status === 'rejected' ? 'Соглашение не достигнуто' : 'Итоги голосования';
      container.append(element('p', statusLabel, 'vote-status'));
      const counts = element('dl', null, 'vote-totals');
      for (const [key, label] of [['for', 'За'], ['against', 'Против'], ['abstain', 'Воздерж.']]) {
        const total = element('div');
        total.append(element('dt', label), element('dd', summary[key]));
        counts.append(total);
      }
      container.append(counts);
      const votes = element('dl', null, 'vote-list');
      for (const vote of summary.votes) {
        const row = element('div');
        row.append(element('dt', this.roleName(vote.role_id)), element('dd', voteLabels[vote.vote] || vote.vote, `vote-${vote.vote}`));
        votes.append(row);
      }
      container.append(votes);
    }

    renderResult() {
      const game = this.game;
      const result = game.result;
      $('result-title').textContent = { completed: 'Итоги партии', cancelled: 'Партия отменена', failed: 'Партия прервана' }[game.status];
      this.notice('result-error', game.error?.message);
      $('retry-result').hidden = !game.available_actions.includes('retry_result');
      $('final-newspaper').hidden = !result;
      $('final-sidebar').hidden = !result && !game.protocol && !game.vote_summary;
      $('final-indicators').hidden = !result;

      this.renderVotes($('final-votes'));
      $('final-protocol').hidden = !game.protocol;
      if (game.protocol) {
        const forecastLabel = game.forecast ? ' и прогноз' : '';
        $('final-protocol-title').textContent = `Протокол №${game.protocol.version}${forecastLabel}`;
        this.renderProtocol($('final-protocol-body'), false);
      }
      if (result) {
        $('outcome-title').textContent = result.outcome_title;
        $('newspaper-horizon').textContent = result.period_months === 120
          ? 'Город через 10 лет' : `Город через ${result.period_months} мес.`;
        $('final-photo').hidden = !result.image_url;
        if (result.image_url) $('consequence-photo').src = result.image_url;
        else $('consequence-photo').removeAttribute('src');
        const paragraphs = (result.herald_text || '').trim().split(/\n\s*\n/).filter(Boolean);
        $('final-text-content').replaceChildren(...paragraphs.map((paragraph) => element('p', paragraph)));
        $('final-indicators').replaceChildren();
        this.renderIndicators($('final-indicators'), result, 'Итоговые показатели');
      }
      const archive = $('journal-archive');
      archive.hidden = this.messages.size === 0;
      archive.append($('journal-content'));
      this.renderJournalCount();
      $('analysis-panel').hidden = game.status !== 'completed';
      if (game.status === 'completed' && !$('analysis-role').options.length) {
        $('analysis-role').replaceChildren(...this.roles.map((role) => new Option(role.name, role.id)));
        this.showAnalysis();
      }
    }

    async requestAnalysis() {
      const game = this.game;
      const roleId = $('analysis-role').value;
      if (game?.status !== 'completed' || !roleId || this.analysisRequest) return;
      const request = { gameId: game.game_id, roleId };
      this.analysisRequest = request;
      this.analysisError = null;
      this.showAnalysis();
      try {
        const report = await api(`/${request.gameId}/analysis`, 'POST', { role_id: roleId });
        if (this.analysisRequest === request) this.analysisResults.set(roleId, report);
      } catch (error) {
        if (this.analysisRequest === request) {
          this.analysisError = { roleId, message: error.message || 'Разбор недоступен. Попробуйте ещё раз.' };
        }
      } finally {
        if (this.analysisRequest === request) {
          this.analysisRequest = null;
          this.showAnalysis();
        }
      }
    }

    showAnalysis() {
      const roleId = $('analysis-role').value;
      const report = this.analysisResults.get(roleId);
      $('request-analysis').disabled = Boolean(this.analysisRequest);
      $('analysis-role').disabled = Boolean(this.analysisRequest);
      this.notice('analysis-status', this.analysisRequest ? 'Готовим разбор по журналу заседания…' : '');
      this.notice('analysis-error', this.analysisError?.roleId === roleId ? this.analysisError.message : '');
      const content = $('analysis-result');
      content.replaceChildren();
      if (!report) return;
      content.append(element('h3', this.roleName(roleId)), element('p', report.paragraph));
      if (report.references.length) {
        content.append(element('h4', 'Реплики из журнала'));
        const quotes = element('ul', null, 'analysis-quotes');
        for (const reference of report.references) {
          const row = element('li');
          const quote = element('blockquote', reference.quote);
          const source = this.messages.get(reference.message_id);
          row.append(quote);
          if (source) {
            const open = element('button', `Перейти к реплике ${source.number}`, 'source-link');
            open.type = 'button';
            open.onclick = () => {
              $('journal-archive').open = true;
              source.item.focus();
              source.item.scrollIntoView({ block: 'center' });
            };
            row.append(open);
          }
          quotes.append(row);
        }
        content.append(quotes);
      }
      if (report.strategy_excerpt) content.append(element('h4', 'Из исходной стратегии'),
        element('blockquote', report.strategy_excerpt));
      if (report.suggested_strategy) content.append(element('h4', 'Что изменить'),
        element('p', report.suggested_strategy));
    }
  }

  document.addEventListener('DOMContentLoaded', () => new GameApp());
})();
