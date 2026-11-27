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
  const fundingLabels = { start_money: 'Первое предложение по взносу', comfort_money: 'Желаемый взнос', max_money: 'Потолок взноса' };
  const picturedRoles = new Set(['city_administration', 'industrial_holding', 'regional_government', 'city_residents', 'environmental_ngo']);
  const formatNumber = new Intl.NumberFormat('ru-RU');
  const savedGame = 'city_n_game_id';
  const draftKey = (id) => `city_n_draft_${id}`;
  const analysisKey = (id) => `city_n_analysis_v2_${id}`;
  const analysisRoleKey = (id) => `city_n_analysis_role_${id}`;
  const analysisRetryDelays = [0, 800, 2000];
  const createKey = 'city_n_create_key';
  const readableValue = (value) => typeof value === 'number' ? formatNumber.format(value) : value;
  const guiltLabels = new Map([
    ['shared', 'Город и холдинг'],
    ['holding', 'Холдинг'],
    ['city', 'Город'],
  ]);

  function conditionValue(id, value) {
    if (id === 'guilt' && guiltLabels.has(value)) return guiltLabels.get(value);
    return typeof value === 'boolean' ? (value ? 'Да' : 'Нет') : readableValue(value);
  }

  function publicText(text) {
    const votes = { for: 'голос «за»', against: 'голос «против»', abstain: 'воздержание', none: 'без голосования' };
    return text
      .replace(/[ \t]*\(\s*vote\s*[:=]\s*["'«]?(?:for|against|abstain|none)\b["'»]?\s*\)/gi, '')
      .replace(/\bvote\s*[:=]\s*["'«]?(for|against|abstain|none)\b["'»]?/gi,
        (_code, vote) => votes[vote.toLowerCase()])
      .replace(/(?:\bguilt\s*[:=]\s*)?["'«]?\bshared\b["'»]?/gi, 'разделённая ответственность');
  }

  function mergeAnalysis(previous, report) {
    if (!report.message_ids) return report;
    const byMessage = new Map();
    for (const finding of [...(previous?.findings || []), ...report.findings]) {
      byMessage.set(finding.references[0].message_id, finding);
    }
    const summary = report.findings.length ? report : previous || report;
    return {
      ...report,
      paragraph: summary.paragraph,
      observation: summary.observation,
      references: summary.references,
      findings: report.message_ids.flatMap((id) => byMessage.has(id) ? [byMessage.get(id)] : []),
      missing_message_ids: report.message_ids.filter((id) => !byMessage.has(id)),
      strategy_excerpt: report.strategy_excerpt ?? previous?.strategy_excerpt,
      suggested_strategy: report.suggested_strategy ?? previous?.suggested_strategy,
    };
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function portrait(roleId) {
    const image = element('img', null, 'role-portrait');
    image.alt = '';
    image.width = image.height = 432;
    if (picturedRoles.has(roleId)) image.src = `assets/tabletop/${roleId}.webp`;
    else image.hidden = true;
    return image;
  }

  function validQuestionValue(question, value) {
    const bounds = question.number_range;
    return bounds ? Number.isInteger(value) && value >= bounds.minimum && value <= bounds.maximum
      : question.options.some((option) => Object.is(option.value, value));
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
      this.analysisFailures = new Set();
      this.questionnaireReviews = new Map();
      this.pollTimer = null;
      this.pollRefresh = false;
      this.busy = false;
      this.inputId = null;
      this.speechReveal = null;

      window.addEventListener('hashchange', () => this.route());
      document.querySelector('.skip-link').onclick = (event) => {
        event.preventDefault();
        $('main').focus();
      };
      $('role-settings').onsubmit = (event) => {
        event.preventDefault();
        const button = $('submit-settings-btn');
        void this.act(async () => {
          button.setAttribute('aria-busy', 'true');
          button.textContent = 'Запускаем партию…';
          try {
            await this.start();
          } finally {
            button.textContent = 'Запустить партию';
            button.removeAttribute('aria-busy');
          }
        });
      };
      const autoDialog = $('auto-settings-dialog');
      $('automatic-settings').onclick = () => this.requestDefaults();
      autoDialog.addEventListener('close', () => {
        if (autoDialog.returnValue === 'confirm' && this.currentScreen === 'settings') void this.fillDefaults();
      });
      $('latest-speech').onclick = () => {
        const item = this.latestSpeech();
        item?.focus({ preventScroll: true });
        this.scrollToSpeech(item);
      };
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
      $('analysis-role').onchange = () => this.resumeAnalysis();
      $('open-assistant').onclick = () => { window.location.hash = 'assistant'; };
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
        this.navigate(window.location.hash === '#instruction' ? 'instruction' : 'start');
        this.notice('game-error', 'Партия недоступна. Начните новую игру.');
      } else {
        this.notice('game-error', error.message || 'Не удалось связаться с сервером.');
      }
    }

    clear() {
      clearTimeout(this.pollTimer);
      this.finishSpeechReveal();
      const id = this.game?.game_id || localStorage.getItem(savedGame);
      if (id) localStorage.removeItem(draftKey(id));
      if (id) {
        try {
          sessionStorage.removeItem(analysisKey(id));
          sessionStorage.removeItem(analysisRoleKey(id));
        } catch { /* Analysis can run with storage disabled. */ }
      }
      localStorage.removeItem(savedGame);
      this.game = this.draft = this.inputId = null;
      this.pollRefresh = false;
      this.cursor = 0;
      this.messages.clear();
      this.rounds.clear();
      this.analysisResults.clear();
      this.analysisFailures.clear();
      this.questionnaireReviews.clear();
      this.analysisRequest = null;
      $('analysis-role').replaceChildren();
      $('analysis-summary').replaceChildren();
      $('analysis-preview-quotes').replaceChildren();
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
      if (window.location.hash === '#instruction') this.screen('instruction');
      const gameId = localStorage.getItem(savedGame);
      if (gameId) {
        this.restoring = true;
        try {
          this.apply(await api(`/${gameId}`), true);
        } catch (error) {
          this.handleError(error);
        } finally {
          this.restoring = false;
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
        const stage = this.gameScreen();
        if (location === 'assistant' && this.game.status === 'completed') this.screen('assistant');
        else if (location === 'debate' && this.game.status === 'completed') this.screen('debate');
        else if (location === 'journal-archive' && stage === 'final' && this.messages.size) this.openArchive();
        else this.navigate(stage);
      } else if (location === 'settings' && !this.restoring) {
        void this.act(async () => {
          const key = sessionStorage.getItem(createKey) || requestKey();
          sessionStorage.setItem(createKey, key);
          const snapshot = await api('', 'POST', undefined, key);
          sessionStorage.removeItem(createKey);
          this.apply(snapshot, true);
        });
      } else if (!this.restoring) {
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

    openArchive(item = $('journal-archive').querySelector('summary')) {
      this.screen('final', 'debate');
      $('journal-archive').open = true;
      item.focus({ preventScroll: true });
      item.scrollIntoView({ block: 'center' });
    }

    screen(name, page = name) {
      const previous = this.currentPage;
      this.currentScreen = name;
      this.currentPage = page;
      if (name !== 'debate') this.finishSpeechReveal();
      const journal = $('journal-content');
      if (name === 'debate' && journal.parentElement !== $('live-journal')) {
        $('live-journal').prepend(journal);
      } else if (name === 'final' && journal.parentElement !== $('journal-archive')) {
        $('debate-feed').querySelectorAll('.speech-new').forEach((item) => item.classList.remove('speech-new'));
        $('journal-archive').append(journal);
      }
      if (name !== 'settings' && $('auto-settings-dialog').open) $('auto-settings-dialog').close('cancel');
      for (const view of document.querySelectorAll('.screen-view')) view.hidden = view.dataset.screenView !== name;
      const stage = this.game ? this.gameScreen() : 'settings';
      const hasArchive = stage === 'final' && this.messages.size > 0;
      const available = new Set(['start', 'instruction', stage]);
      if (hasArchive) available.add('debate');
      if (this.game?.status === 'completed') available.add('assistant');
      for (const link of document.querySelectorAll('.site-nav a')) {
        const destination = link.dataset.page;
        link.hidden = !available.has(destination);
        if (destination === 'debate') link.href = hasArchive && name !== 'debate' ? '#journal-archive' : '#debate';
        if (destination === page) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      }
      if (name !== 'instruction') document.querySelector('video').pause();
      if (name === 'start') {
        const link = $('start-link');
        link.href = `#${stage}`;
        const labels = { settings: 'Настроить агентов', debate: 'Вернуться к переговорам', final: 'Посмотреть итоги' };
        link.textContent = labels[stage];
      }
      if (name === 'instruction') {
        const labels = { settings: 'К анкетам', debate: 'К переговорам', final: 'К итогам' };
        const link = $('rules-return');
        link.href = `#${stage}`;
        link.textContent = labels[stage];
      }
      if (name === 'assistant') this.resumeAnalysis();
      if (previous !== page) {
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
      if (snapshot.status === 'running' || snapshot.status === 'completed') this.renderDebate();
      if (['completed', 'cancelled', 'failed'].includes(snapshot.status)) this.renderResult();
      this.route();
      if (recover && snapshot.status === 'running') this.schedulePoll();
    }

    initSettings() {
      const settings = this.game.settings;
      this.questionnaires = this.game.scenario.questionnaires;
      const stored = localStorage.getItem(draftKey(this.game.game_id));
      let savedDraft;
      try { savedDraft = JSON.parse(stored); } catch (_) { savedDraft = null; }
      $('setup-card').hidden = !this.questionnaires;
      this.notice('setup-auto-error');
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

    requestDefaults() {
      const dialog = $('auto-settings-dialog');
      if (dialog.open || this.busy || this.game?.status !== 'draft') return;
      const hasManualAnswers = this.draft.mode === 'manual'
        && Object.values(this.draft.answers).some((answers) => Object.keys(answers).length);
      if (hasManualAnswers) {
        dialog.returnValue = '';
        dialog.showModal();
      } else void this.fillDefaults();
    }

    async fillDefaults() {
      if (this.game?.status !== 'draft') return;
      const id = this.game.game_id;
      const button = $('automatic-settings');
      await this.act(async () => {
        button.setAttribute('aria-busy', 'true');
        button.textContent = 'Подготавливаем анкеты…';
        $('setup-card').dataset.state = 'pending';
        this.notice('setup-auto-error');
        this.notice('setup-mode', 'Проверяем настройки пяти сторон на сервере.');
        try {
          const snapshot = await api(`/${id}/settings`, 'PUT', { mode: 'automatic' });
          if (this.game?.game_id !== id) return;
          this.apply(snapshot);
          this.draft = {
            mode: 'automatic',
            usedDefaults: true,
            selectedRole: this.selectedRole,
            answers: Object.fromEntries(snapshot.settings.roles.map((role) => [role.role_id, role.answers])),
          };
          this.saveDraft();
          this.selectRole(this.selectedRole);
        } catch (error) {
          if (error.status === 404 || error.status === 409) throw error;
          this.notice('setup-auto-error', error.message || 'Повторите автонастройку.');
        } finally {
          button.textContent = 'Настроить автоматически';
          button.removeAttribute('aria-busy');
          if (this.game?.game_id === id) this.renderSettingsNav();
        }
      });
    }

    missingQuestion(roleId) {
      const answers = this.draft.answers[roleId];
      return this.questionnaires[roleId].fields.find((field) => field.required
        && !validQuestionValue(field, answers[field.id]));
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
      header.dataset.roleId = roleId;
      const description = element('div');
      description.append(heading);
      if (role.interest) description.append(element('p', role.interest));
      header.append(portrait(roleId), description);
      form.replaceChildren(header);
      if (this.questionnaires) this.renderQuestions(form, roleId);
      else this.renderLegacySettings(form, roleId);
      this.renderSettingsNav();
    }

    renderSettingsNav() {
      const nav = $('roles-nav');
      if (!nav.children.length || nav.firstChild.dataset.game !== this.game.game_id) {
        nav.replaceChildren();
        for (const role of this.roles) {
          const row = element('li');
          row.dataset.game = this.game.game_id;
          const button = element('button', null, 'role-link');
          button.dataset.roleId = role.id;
          const mark = element('span', '', 'role-check');
          mark.setAttribute('aria-hidden', 'true');
          const indicator = element('span', '', 'sr-only');
          button.append(portrait(role.id), element('span', role.name), mark, indicator);
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
        const meter = $('settings-meter');
        meter.hidden = false;
        meter.max = this.roles.length;
        meter.value = completed;
      } else {
        $('settings-progress').textContent = '';
        $('settings-meter').hidden = true;
      }
      const failed = !$('setup-auto-error').hidden;
      $('setup-card').dataset.state = failed ? 'error' : this.draft.mode === 'automatic' ? 'ready' : 'idle';
      const message = failed ? '' : this.draft.mode === 'automatic' ? 'Настройки пяти сторон готовы. Можно запускать партию.'
        : this.draft.usedDefaults ? 'Автоматические ответы отредактированы. Партия запустится с ручными настройками.' : '';
      this.notice('setup-mode', message);
      $('next-role').hidden = this.selectedRole === this.roles.at(-1).id;
    }

    renderQuestions(form, roleId) {
      const answers = this.draft.answers[roleId];
      const budget = element('section', null, 'questionnaire-section funding-section');
      const budgetHeader = element('header', null, 'question-group-heading');
      const reserve = this.game.scenario.role_settings_schema?.[roleId]?.pledged_rub_max;
      budgetHeader.append(element('h3', 'Бюджет стороны'));
      if (Number.isInteger(reserve)) budgetHeader.append(element('span', `${formatNumber.format(reserve / 1_000_000)} млн ₽`));
      budget.append(budgetHeader);
      const terms = element('section', null, 'questionnaire-section');
      terms.append(element('header', null, 'question-group-heading'));
      terms.firstChild.append(element('h3', 'Условия переговоров'));
      for (const question of this.questionnaires[roleId].fields) {
        const value = answers[question.id];
        const funding = Object.hasOwn(fundingLabels, question.id) || (roleId === 'city_administration' && question.id === 'water_supply');
        const group = funding ? budget : terms;
        const update = (answer) => {
          if (answer === undefined) delete answers[question.id];
          else answers[question.id] = answer;
          this.draft.mode = 'manual';
          this.renderSettingsNav();
        };
        if (question.number_range) {
          this.settingRange(group, question, value, update);
        } else if (question.options.length) {
          this.settingOptions(group, roleId, question, value, update);
        } else {
          const input = Object.assign(element('textarea'), { value: value ?? '', rows: 3, maxLength: 6000 });
          input.placeholder = 'Ваши аргументы или условия';
          input.required = question.required;
          this.settingField(group, question.label, question.id, input, (field) => update(field.value), question.hint);
        }
      }
      if (budget.childElementCount > 1) form.append(budget);
      form.append(terms);
    }

    settingRange(form, question, value, update) {
      const { minimum, maximum, unit } = question.number_range;
      const id = `question-${question.id}`;
      const wrapper = element('div', null, 'question range-question');
      const label = element('label', fundingLabels[question.id] || question.label, 'range-label');
      label.htmlFor = id;
      label.id = `${id}-label`;
      const number = Object.assign(element('input'), {
        id, type: 'number', min: minimum, max: maximum, step: 1, inputMode: 'numeric',
        required: question.required, value: value ?? '',
      });
      number.dataset.path = question.id;
      const slider = Object.assign(element('input'), { type: 'range', min: minimum, max: maximum, step: 1 });
      slider.setAttribute('aria-labelledby', label.id);
      if (question.hint) {
        const hint = element('p', question.hint, 'question-hint');
        hint.id = `${id}-hint`;
        slider.setAttribute('aria-describedby', hint.id);
        number.setAttribute('aria-describedby', hint.id);
        wrapper.append(label, hint);
      } else wrapper.append(label);
      const control = element('div', null, 'range-control');
      const track = element('div', null, 'range-track');
      const limits = element('div', null, 'range-limits');
      limits.append(element('span', `${minimum} ${unit}`), element('span', `${maximum} ${unit}`));
      track.append(slider, limits);
      const exact = element('div', null, 'range-amount');
      exact.append(number, element('span', unit));
      control.append(track, exact);
      wrapper.append(control);
      form.append(wrapper);

      const reflect = (answer) => {
        slider.value = answer ?? minimum;
        const fraction = (slider.valueAsNumber - minimum) / (maximum - minimum);
        slider.style.setProperty('--fill', `${fraction * 100}%`);
        slider.setAttribute('aria-valuetext', answer === undefined ? `Без ответа, от ${minimum} до ${maximum} ${unit}`
          : `${slider.value} ${unit}`);
        if (answer === undefined || validQuestionValue(question, answer)) number.removeAttribute('aria-invalid');
        else number.setAttribute('aria-invalid', 'true');
      };
      const save = (answer) => {
        this.clearFieldError(number);
        reflect(answer);
        update(answer);
        this.saveDraft();
      };
      slider.oninput = () => {
        number.value = slider.value;
        save(slider.valueAsNumber);
      };
      number.oninput = () => save(number.value === '' ? undefined : number.valueAsNumber);
      reflect(value);
    }

    settingOptions(form, roleId, question, value, update) {
      const wrapper = element('div', null, 'question');
      const group = element('fieldset', null, 'question-option-group');
      const id = `question-${roleId}-${question.id}`;
      group.append(element('legend', question.label));
      if (question.hint) {
        const hint = element('p', question.hint, 'question-hint');
        hint.id = `${id}-hint`;
        group.setAttribute('aria-describedby', hint.id);
        group.append(hint);
      }
      const options = element('div', null, 'question-options');
      for (const [index, option] of question.options.entries()) {
        const input = Object.assign(element('input'), {
          type: 'radio', name: id, id: `${id}-${index}`, value: String(index),
          checked: Object.is(option.value, value), required: question.required,
        });
        input.dataset.path = question.id;
        const label = element('label', null, 'question-option');
        const copy = element('span', option.label);
        if (roleId === 'city_administration' && question.id === 'water_supply' && typeof option.value === 'boolean') {
          const details = element('small', option.label.match(/\(([^()]*)\)$/)?.[1] || option.label);
          copy.textContent = option.value ? 'Включить подвоз' : 'Без подвоза воды';
          copy.append(details);
        }
        label.append(input, copy);
        options.append(label);
        input.onchange = () => {
          this.clearFieldError(input);
          update(option.value);
          this.saveDraft();
        };
      }
      group.append(options);
      wrapper.append(group);
      form.append(wrapper);
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
        if (condition.allowed) field = this.select(condition.allowed.map((option) => [option, conditionValue(condition.id, option)]), value);
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
        this.clearFieldError(field);
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

    clearFieldError(field) {
      const question = field.closest('.question');
      const invalid = question?.querySelector('[aria-invalid]');
      invalid?.removeAttribute('aria-invalid');
      invalid?.removeAttribute('aria-errormessage');
      question?.querySelector('.field-error')?.remove();
      this.notice('settings-error');
    }

    settingsError(roleId, path, message) {
      this.selectRole(roleId);
      const fields = Array.from($('role-settings').elements).filter((item) => item.dataset.path === path);
      const field = fields.find((item) => item.checked) || fields[0];
      if (field) {
        const feedback = element('p', message, 'field-error');
        feedback.id = 'field-error';
        feedback.setAttribute('role', 'alert');
        field.closest('.question').append(feedback);
        field.setAttribute('aria-invalid', 'true');
        field.setAttribute('aria-errormessage', feedback.id);
      } else this.notice('settings-error', message);
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
          const bounds = missing.number_range;
          const message = bounds ? `Введите целое число от ${bounds.minimum} до ${bounds.maximum} ${bounds.unit}.`
            : `Ответьте на обязательные вопросы анкеты «${this.roleName(roleId)}».`;
          this.settingsError(roleId, missing.id, message);
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
        const live = this.currentScreen === 'debate' && !document.hidden;
        const latest = this.latestSpeech();
        const following = live && (!latest || latest.getBoundingClientRect().bottom <= window.innerHeight + 48);
        const newest = live && page.events.findLast(event => event.type === 'message.created'
          && !this.messages.has(event.payload.message_id));
        let added = 0;
        for (const event of page.events) {
          if (event.type === 'message.created') {
            if (this.append(event.payload, {
              animationDelay: live ? Math.min(added * 65, 195) : null,
              reveal: event === newest,
              follow: following,
            })) added++;
          }
          else this.pollRefresh = true;
        }
        if (added && following) this.scrollToSpeech($('current-speaker').hidden ? this.latestSpeech() : $('current-speaker'));
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

    latestSpeech() {
      return [...this.messages.values()].at(-1)?.item;
    }

    scrollToSpeech(item) {
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const position = item?.getBoundingClientRect();
      if (position && (position.bottom > window.innerHeight || position.top < 0)) {
        item.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'nearest' });
      }
    }

    append(message, { animationDelay = null, reveal = false, follow = false } = {}) {
      if (this.messages.has(message.message_id)) return false;
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
      item.dataset.roleId = message.role_id;
      if (message.skipped) item.classList.add('speech-skipped');
      if (animationDelay !== null) {
        item.classList.add('speech-new');
        item.style.setProperty('--speech-delay', `${animationDelay}ms`);
        item.addEventListener('animationend', () => item.classList.remove('speech-new'), { once: true });
      }
      item.tabIndex = -1;
      const meta = element('span', `Реплика ${number}`, 'speech-number');
      const copy = element('div', null, 'speech-copy');
      const heading = element('div', null, 'speech-heading');
      heading.append(element('h3', this.roleName(message.role_id), 'speech-role'), meta);
      const text = element('p', publicText(message.content), 'speech-text');
      copy.append(heading, text);
      item.append(portrait(message.role_id), copy);
      entry.append(item);
      list.append(entry);
      this.messages.set(message.message_id, { item, number });
      this.renderJournalCount();
      if (reveal) {
        this.finishSpeechReveal();
        if (!message.skipped) this.revealSpeech(item, text, follow);
      }
      return true;
    }

    revealSpeech(item, paragraph, follow) {
      const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
      const content = paragraph.textContent;
      const ends = Array.from(content.matchAll(/\S+\s*/gu), (word) => word.index + word[0].length);
      if (motion.matches || ends.length < 5) return;

      paragraph.setAttribute('aria-busy', 'true');
      item.classList.add('speech-revealing');
      const reveal = { item, paragraph, content, frame: null };
      this.speechReveal = reveal;
      const begin = performance.now();
      const duration = Math.max(520, Math.min(2800, (ends.length - 2) * 42));
      let visible = 2;
      paragraph.textContent = content.slice(0, ends[visible - 1]);
      const show = (now) => {
        if (this.speechReveal !== reveal) return;
        const elapsed = Math.max(0, now - begin);
        if (elapsed >= duration || motion.matches || document.hidden) {
          this.finishSpeechReveal();
          return;
        }
        const next = 2 + Math.floor((ends.length - 2) * elapsed / duration);
        if (next > visible) {
          const bottom = item.getBoundingClientRect().bottom;
          paragraph.textContent = content.slice(0, ends[next - 1]);
          visible = next;
          if (follow && bottom <= window.innerHeight + 32 && item.getBoundingClientRect().bottom > window.innerHeight) {
            item.scrollIntoView({ behavior: 'instant', block: 'end' });
          }
        }
        reveal.frame = requestAnimationFrame(show);
      };
      reveal.frame = requestAnimationFrame(show);
    }

    finishSpeechReveal() {
      if (!this.speechReveal) return;
      const { item, paragraph, content, frame } = this.speechReveal;
      cancelAnimationFrame(frame);
      paragraph.textContent = content;
      paragraph.removeAttribute('aria-busy');
      item.classList.remove('speech-revealing');
      this.speechReveal = null;
    }

    renderJournalCount() {
      const count = this.messages.size;
      $('empty-journal').hidden = !!count || !!this.game.current_role_id;
      $('latest-speech').hidden = !count;
      const limit = this.game.scenario.max_dialogue_messages;
      $('journal-progress').textContent = limit ? `${count} / ${limit} реплик` : `Реплик: ${count}`;
      const meter = $('journal-meter');
      meter.hidden = !limit;
      if (limit) { meter.max = limit; meter.value = count; }
      $('archive-count').textContent = `Реплик: ${count}`;
    }

    renderDebate() {
      const game = this.game;
      const actions = game.available_actions;
      const completed = game.status === 'completed';
      this.renderJournalCount();
      const pause = game.pause_state === 'requested' ? ' · Пауза запрошена' : game.pause_state === 'paused' ? ' · Пауза' : '';
      $('phase-title').textContent = completed ? 'Заседание завершено' : (phaseLabels[game.phase] || 'Подготовка участников') + pause;
      $('newspaper-action').hidden = !completed || !game.result;
      const roster = $('debate-roles');
      if (roster.dataset.gameId !== game.game_id) {
        roster.dataset.gameId = game.game_id;
        roster.replaceChildren(...this.roles.map((role) => {
          const card = element('li');
          card.dataset.roleId = role.id;
          card.append(portrait(role.id), element('span', role.name));
          return card;
        }));
      }
      for (const card of roster.children) {
        if (card.dataset.roleId === game.current_role_id) card.setAttribute('aria-current', 'true');
        else card.removeAttribute('aria-current');
      }
      const speaker = $('current-speaker');
      speaker.hidden = !game.current_role_id;
      if (game.current_role_id && speaker.dataset.roleId !== game.current_role_id) {
        speaker.dataset.roleId = game.current_role_id;
        const text = element('div');
        text.append(element('small'), element('strong', this.roleName(game.current_role_id)));
        speaker.replaceChildren(portrait(game.current_role_id), text);
      }
      if (game.current_role_id) {
        const caption = game.pause_state !== 'none' ? 'Пауза' : game.pending_input ? 'Текущий ход'
          : game.phase === 'voting' ? 'Голосует' : 'Готовит реплику';
        const status = speaker.querySelector('small');
        if (status.textContent !== caption) status.textContent = caption;
      }
      $('pause-btn').textContent = game.pause_state === 'none' ? 'Приостановить' : 'Продолжить';
      $('pause-btn').hidden = !actions.includes('pause') && !actions.includes('continue');
      $('stop-btn').hidden = !actions.includes('cancel');

      const agenda = $('hearing-agenda');
      agenda.replaceChildren();
      const phases = Object.keys(phaseLabels);
      for (const [index, phase] of phases.entries()) {
        const item = element('li', phaseLabels[phase]);
        if (phase === game.phase) item.setAttribute('aria-current', 'step');
        if (completed || index < phases.indexOf(game.phase)) item.className = 'phase-passed';
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
        const value = conditionValue(item.item_id, item.value);
        const group = element('div');
        group.append(element('dt', item.item_id === 'guilt' ? 'Ответственность за аварию' : item.title));
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
        row.dataset.roleId = vote.role_id;
        row.append(element('dt', this.roleName(vote.role_id)), element('dd', voteLabels[vote.vote] || vote.vote, `vote-${vote.vote}`));
        votes.append(row);
      }
      container.append(votes);
    }

    renderResult() {
      const game = this.game;
      const result = game.result;
      $('result-title').textContent = { completed: 'Итоги партии', cancelled: 'Партия отменена', failed: 'Партия прервана' }[game.status];
      const cancelled = game.status === 'cancelled';
      this.notice('result-state-copy', cancelled ? (this.messages.size ? 'Сохранённые реплики доступны в журнале ниже.'
        : 'Заседание завершилось до первой реплики.') : '');
      $('finish-game').textContent = result ? 'Завершить партию' : 'К началу';
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
      $('journal-archive').hidden = this.messages.size === 0;
      this.renderJournalCount();
      $('analysis-panel').hidden = game.status !== 'completed';
      $('open-assistant').hidden = game.status !== 'completed';
      if (game.status === 'completed' && !$('analysis-role').options.length) {
        $('analysis-role').replaceChildren(...this.roles.map((role) => new Option(role.name, role.id)));
        try {
          const saved = JSON.parse(sessionStorage.getItem(analysisKey(game.game_id)) || '[]');
          for (const [roleId, report] of saved) this.analysisResults.set(roleId, report);
          const roleId = sessionStorage.getItem(analysisRoleKey(game.game_id));
          if (this.roles.some((role) => role.id === roleId)) $('analysis-role').value = roleId;
        } catch { this.analysisResults.clear(); }
        this.showAnalysis();
      }
    }

    analysisMessages(roleId) {
      return this.game.messages.filter((message) => message.role_id === roleId
        && !message.skipped && message.content.trim());
    }

    resumeAnalysis() {
      const roleId = $('analysis-role').value;
      if (this.questionnaireReviews.get(roleId) === false) this.questionnaireReviews.delete(roleId);
      this.showAnalysis();
      try { sessionStorage.setItem(analysisRoleKey(this.game.game_id), roleId); }
      catch { /* Analysis can run with storage disabled. */ }
      if (this.analysisResults.get(roleId)?.missing_message_ids?.length) void this.requestAnalysis();
    }

    async requestAnalysis() {
      const game = this.game;
      const roleId = $('analysis-role').value;
      if (game?.status !== 'completed' || !roleId || this.analysisRequest || this.analysisFailures.has(roleId)
          || !this.analysisMessages(roleId).length) return;
      let previous = this.analysisResults.get(roleId);
      if (previous && !previous.missing_message_ids?.length) return;
      const request = { retrying: Boolean(previous) };
      this.analysisRequest = request;
      this.showAnalysis();
      let complete = false;
      try {
        for (const [attempt, delay] of analysisRetryDelays.entries()) {
          if (delay) {
            request.retrying = true;
            this.showAnalysis();
            await new Promise((resolve) => setTimeout(resolve, delay));
          }
          if (this.analysisRequest !== request) return;
          const input = { role_id: roleId };
          if (previous?.missing_message_ids?.length) input.message_ids = previous.missing_message_ids;
          if (attempt === analysisRetryDelays.length - 1) input.complete_from_journal = true;
          let report;
          try {
            report = await api(`/${game.game_id}/analysis`, 'POST', input);
          } catch (error) {
            if (this.analysisRequest !== request) return;
            if (error.status && error.status < 500 && ![408, 429].includes(error.status)) break;
            continue;
          }
          if (this.analysisRequest !== request) return;
          previous = mergeAnalysis(previous, report);
          this.analysisResults.set(roleId, previous);
          try { sessionStorage.setItem(analysisKey(game.game_id), JSON.stringify([...this.analysisResults])); }
          catch { /* Keep the report in memory when browser storage is unavailable. */ }
          complete = !previous.missing_message_ids?.length;
          if (complete) break;
        }
      } finally {
        if (this.analysisRequest === request) {
          if (!complete) this.analysisFailures.add(roleId);
          this.analysisRequest = null;
          this.showAnalysis();
          if (complete && document.activeElement === $('request-analysis')) {
            $('analysis-result-title')?.focus();
          }
        }
      }
    }

    showAnalysis() {
      const roleId = $('analysis-role').value;
      const report = this.analysisResults.get(roleId);
      const messages = this.analysisMessages(roleId);
      const pending = this.analysisRequest;
      const failed = this.analysisFailures.has(roleId);
      const submit = $('request-analysis');
      const complete = Boolean(report && !report.missing_message_ids?.length);
      const ready = complete && !pending;
      const answers = this.game.settings.roles.find((role) => role.role_id === roleId)?.answers;
      const canReviewQuestionnaire = answers && Object.keys(answers).length > 0;
      const questionnaireOnly = canReviewQuestionnaire && (failed || !messages.length);
      submit.textContent = !messages.length ? 'Нет реплик для разбора'
        : pending ? 'Готовим разбор' : complete ? 'Разбор готов'
        : failed ? 'Разбор завершён' : 'Разобрать переговоры';
      submit.setAttribute('aria-disabled', String(Boolean(pending || complete || failed || !messages.length)));
      submit.setAttribute('aria-busy', String(Boolean(pending)));
      $('analysis-role').disabled = Boolean(pending);
      const status = pending?.retrying ? 'Помощник заново готовит недостающие оценки…'
        : pending ? 'Помощник читает реплики в журнале…' : '';
      this.notice('analysis-status', status);
      this.notice('analysis-error', failed ? 'Помощнику не удалось подготовить полный разбор.' : '');
      const summary = $('analysis-summary');
      if (summary.dataset.roleId !== roleId || !summary.firstChild) {
        summary.dataset.roleId = roleId;
        summary.replaceChildren(portrait(roleId), element('h2', this.roleName(roleId)));
      }
      const preview = $('analysis-preview');
      preview.hidden = ready;
      if (!ready) {
        const quotes = $('analysis-preview-quotes');
        if (quotes.dataset.roleId !== roleId || !quotes.firstChild) {
          quotes.dataset.roleId = roleId;
          quotes.replaceChildren();
          const sources = messages.map((message) => ({ message_id: message.message_id, quote: message.content }));
          if (sources.length) this.appendAnalysisEvidence(quotes, sources, true);
          else quotes.append(element('p', 'У этой стороны нет реплик в журнале.', 'analysis-coverage'));
        }
      }
      const content = $('analysis-result');
      const sourceOpen = content.dataset.roleId === roleId && content.querySelector('.strategy-source')?.open;
      content.dataset.roleId = roleId;
      content.hidden = !ready && !questionnaireOnly;
      content.replaceChildren();
      if (!ready) {
        if (questionnaireOnly) content.append(this.analysisQuestionnaire(roleId));
        return;
      }

      const structured = Boolean(report.findings?.length);
      const title = element('h2', 'Разбор реплик', 'analysis-section-title');
      title.id = 'analysis-result-title';
      title.tabIndex = -1;
      const overview = element('header', null, 'analysis-overview');
      overview.append(title);
      content.append(overview);
      const body = element('div', null, 'analysis-body');
      if (report.message_ids || structured) {
        if (report.message_ids) {
          overview.append(element('p', `Разобрано ${report.findings.length} из ${report.message_ids.length} реплик.`,
            'analysis-coverage'));
        }
        const findings = element('div', null, 'analysis-findings');
        findings.append(...report.findings.map((finding) => this.analysisFinding(finding)));
        body.append(findings);
      } else {
        const legacy = element('section', null, 'analysis-card');
        legacy.append(element('h3', 'Разбор хода'), element('p', publicText(report.observation || report.paragraph)));
        this.appendAnalysisEvidence(legacy, report.references, Boolean(report.observation));
        body.append(legacy);
      }
      if (canReviewQuestionnaire) {
        body.append(this.analysisQuestionnaire(roleId));
      } else if (report.suggested_strategy && report.strategy_excerpt) {
        body.append(this.analysisStrategy(report, roleId, sourceOpen));
      }
      content.append(body);
    }

    analysisFinding(finding) {
      const card = element('section', null, 'analysis-card analysis-finding');
      card.dataset.verdict = finding.verdict;
      const heading = element('header', null, 'finding-header');
      const move = this.messages.get(finding.references[0].message_id);
      const verdictLabel = { keep: 'Удачный ход', improve: 'Можно улучшить', neutral: 'Наблюдение' };
      heading.append(element('h3', move ? `Реплика ${move.number}` : 'Ход стороны'),
        element('span', verdictLabel[finding.verdict], 'finding-verdict'));
      card.append(heading, element('p', publicText(finding.observation), 'finding-observation'));
      this.appendAnalysisEvidence(card, finding.references, true);
      if (finding.next_reply) {
        const alternative = element('div', null, 'finding-alternative');
        const label = finding.verdict === 'improve' ? 'Что можно было сказать' : 'Как продолжить';
        alternative.append(element('h4', label), element('p', publicText(finding.next_reply)));
        card.append(alternative);
      }
      return card;
    }

    appendAnalysisEvidence(container, references, showQuote) {
      const list = element('ul', null, 'analysis-quotes');
      for (const reference of references) {
        const source = this.messages.get(reference.message_id);
        if (!source && !showQuote) continue;
        const row = element('li');
        if (source) {
          const author = this.roleName(source.item.dataset.roleId);
          const meta = `Реплика ${source.number} · ${author}`;
          const caption = 'Открыть в журнале';
          const button = element('button', null, 'source-link');
          button.type = 'button';
          button.setAttribute('aria-label', `${caption}. ${meta}`);
          button.append(element('span', meta, 'source-meta'));
          if (showQuote) {
            const quote = publicText(reference.quote);
            button.setAttribute('aria-description', quote);
            button.append(element('span', quote, 'source-quote'));
          }
          button.append(element('span', caption, 'source-caption'));
          button.onclick = () => {
            history.pushState(null, '', '#journal-archive');
            this.openArchive(source.item);
          };
          row.append(button);
        } else {
          row.append(element('blockquote', publicText(reference.quote)));
        }
        list.append(row);
      }
      if (list.childElementCount) container.append(list);
    }

    async loadQuestionnaireReview(roleId) {
      const gameId = this.game.game_id;
      this.questionnaireReviews.set(roleId, null);
      const review = await api(`/${gameId}/analysis/questionnaire/${encodeURIComponent(roleId)}`).catch(() => false);
      if (this.game?.game_id !== gameId) return;
      this.questionnaireReviews.set(roleId, review);
      if (this.currentScreen === 'assistant' && $('analysis-role').value === roleId) this.showAnalysis();
    }

    analysisQuestionnaire(roleId) {
      const section = element('section', null, 'analysis-card analysis-strategy');
      section.setAttribute('aria-labelledby', 'questionnaire-review-title');
      const title = element('h3', 'Что изменить в анкете');
      title.id = 'questionnaire-review-title';
      section.append(title);

      const review = this.questionnaireReviews.get(roleId);
      if (review === undefined) void this.loadQuestionnaireReview(roleId);
      if (!review) {
        const status = element('p', review === false ? 'Не удалось загрузить рекомендации по анкете.'
          : 'Подбираем ответы для следующей партии…', 'analysis-coverage');
        status.setAttribute('role', 'status');
        section.append(status);
        return section;
      }
      if (review.context) section.append(element('p', review.context, 'analysis-coverage'));
      const recommendations = element('div', null, 'questionnaire-review');
      for (const item of review.items) {
        const entry = element('div', null, 'questionnaire-advice');
        entry.append(element('h4', item.question));
        const current = element('div', null, 'strategy-original');
        current.append(element('dt', 'Выбранный ответ'), element('dd', item.chosen));
        const next = element('div', null, 'strategy-proposal');
        next.append(element('dt', item.chosen === item.suggested ? 'Сохранить этот ответ' : 'В следующей партии'),
          element('dd', item.suggested));
        const answers = element('dl');
        answers.append(current, next);
        entry.append(answers, element('p', item.reason));
        recommendations.append(entry);
      }
      section.append(recommendations);
      return section;
    }

    analysisStrategy(report, roleId, sourceOpen) {
      const card = element('section', null, 'analysis-card analysis-strategy');
      card.setAttribute('aria-labelledby', 'strategy-adjustment-title');
      const title = element('h3', 'Правка стратегии');
      title.id = 'strategy-adjustment-title';
      const excerpt = publicText(report.strategy_excerpt);
      const original = element('div', null, 'strategy-original');
      original.append(element('dt', 'В сыгранной партии'), element('dd', excerpt));
      const proposal = element('div', null, 'strategy-proposal');
      proposal.append(element('dt', 'В следующей партии'), element('dd', publicText(report.suggested_strategy)));
      const changes = element('dl');
      changes.append(original, proposal);
      card.append(title, changes);
      const strategy = publicText(this.game.settings.roles.find((role) => role.role_id === roleId)?.strategy ?? '');
      const start = excerpt ? strategy.indexOf(excerpt) : -1;
      if (start !== -1) {
        const prompt = element('pre');
        prompt.append(strategy.slice(0, start), element('mark', excerpt), strategy.slice(start + excerpt.length));
        const disclosure = element('details', null, 'strategy-source');
        disclosure.open = Boolean(sourceOpen);
        disclosure.append(element('summary', 'Открыть исходную стратегию'), prompt);
        card.append(disclosure);
      }
      return card;
    }
  }

  document.addEventListener('DOMContentLoaded', () => new GameApp());
})();
