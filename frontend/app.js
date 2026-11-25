(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const phaseLabels = {
    positions: 'Раунд 1. Позиции', negotiation: 'Раунд 2. Переговоры', amendments: 'Раунд 3. Поправки',
    preparing_protocol: 'Подготовка протокола', forecasting: 'Расчёт прогноза', voting: 'Голосование',
    calculating_result: 'Расчёт последствий',
  };
  const voteLabels = { for: 'За', against: 'Против', abstain: 'Воздержался' };
  const formatNumber = new Intl.NumberFormat('ru-RU');
  const savedGame = 'city_n_game_id';
  const draftKey = (id) => `city_n_draft_${id}`;
  const createKey = 'city_n_create_key';

  function element(tag, text) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    return node;
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
    const payload = await response.json();
    if (!response.ok) throw Object.assign(new Error(payload.message || 'Запрос не выполнен.'), payload, { status: response.status });
    return payload;
  }

  class GameApp {
    constructor() {
      this.game = null;
      this.draft = null;
      this.cursor = 0;
      this.pollTimer = null;
      this.messageIds = new Set();
      this.pollRefresh = false;
      this.busy = false;
      this.inputId = null;

      window.addEventListener('hashchange', () => this.route());
      $('role-settings').addEventListener('submit', (event) => {
        event.preventDefault();
        void this.act(() => this.start());
      });
      $('manual-input').addEventListener('submit', (event) => {
        event.preventDefault();
        const pending = this.game?.pending_input;
        if (!pending || pending.input_id !== this.inputId) return;
        const data = new FormData(event.currentTarget);
        const value = pending.type === 'speech' ? { type: 'speech', content: data.get('content') }
          : { type: 'vote', vote: data.get('vote') };
        void this.act(() => this.command(`/inputs/${pending.input_id}`, value));
      });
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
      $('finish-game').onclick = () => this.clear();
      $('exit-btn').onclick = () => window.close();
      void this.restore();
    }

    showError(message = '') {
      $('game-error').textContent = message;
      $('game-error').hidden = !message;
    }

    async act(callback) {
      if (this.busy) return;
      this.busy = true;
      $('submit-settings-btn').disabled = true;
      this.showError();
      try {
        await callback();
      } catch (error) {
        this.handleError(error);
      } finally {
        this.busy = false;
        $('submit-settings-btn').disabled = false;
      }
    }

    handleError(error) {
      if (error.status === 404 && error.code !== 'ROLE_NOT_FOUND') {
        this.clear();
        this.navigate('start');
        this.showError('Партия недоступна. Начните новую игру.');
      } else {
        this.showError(error.message || 'Не удалось связаться с сервером.');
      }
    }

    clear() {
      clearTimeout(this.pollTimer);
      const id = this.game?.game_id || localStorage.getItem(savedGame);
      if (id) localStorage.removeItem(draftKey(id));
      localStorage.removeItem(savedGame);
      this.game = this.draft = this.inputId = null;
      this.pollRefresh = false;
      this.messageIds.clear();
      $('debate-feed').replaceChildren();
    }

    async restore() {
      const gameId = localStorage.getItem(savedGame);
      if (gameId) {
        try {
          this.apply(await api(`/${gameId}`), true);
        } catch (error) {
          this.handleError(error);
        }
        return;
      }
      this.route();
    }

    route() {
      const location = window.location.hash.slice(1);
      if (location === 'instruction') {
        this.screen('instruction');
      } else if (this.game) {
        this.navigate(this.game.status === 'draft' ? 'settings' : this.game.status === 'running' ? 'debate' : 'final');
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

    navigate(name) {
      if (window.location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
      this.screen(name);
    }

    screen(name) {
      const frame = document.querySelector('.screen-frame');
      if (frame.dataset.currentScreen !== name) $('main-info-col').scrollTop = 0;
      frame.dataset.currentScreen = name;
      for (const view of document.querySelectorAll('.screen-view, .menu-view')) {
        view.classList.toggle('active', (view.dataset.screenView || view.dataset.menuView) === name);
      }
      if (name === 'instruction') $('instruction-video').play().catch(() => {});
      else $('instruction-video').pause();
    }

    apply(snapshot, recover = false) {
      if (!recover && this.game?.game_id !== snapshot.game_id) return;
      if (!recover && snapshot.last_event_id < this.game.last_event_id) return;
      const previous = this.game;
      this.game = snapshot;
      localStorage.setItem(savedGame, snapshot.game_id);
      if (recover) {
        this.cursor = snapshot.last_event_id;
        for (const message of snapshot.messages) this.append(message, false);
      }
      if (snapshot.status === 'draft' && (!previous || !this.draft)) this.initSettings();
      if (snapshot.status === 'running') this.renderDebate();
      if (['completed', 'cancelled', 'failed'].includes(snapshot.status)) this.renderResult();
      this.route();
      if (recover && snapshot.status === 'running') this.schedulePoll();
    }

    initSettings() {
      const settings = this.game.settings.roles.map(({ spent_on_conditions_rub, ...role }) => role);
      const stored = localStorage.getItem(draftKey(this.game.game_id));
      try { this.draft = stored ? JSON.parse(stored) : settings; } catch (_) { this.draft = settings; }
      this.selectRole(this.draft[0].role_id);
    }

    selectRole(roleId) {
      const nav = $('roles-nav');
      nav.replaceChildren();
      for (const role of this.game.scenario.roles) {
        const button = element('button', role.name);
        button.type = 'button';
        button.className = 'menu-btn';
        button.classList.toggle('active', roleId === role.id);
        button.onclick = () => this.selectRole(role.id);
        nav.append(button);
      }
      const form = $('role-settings');
      const draft = this.draft.find((role) => role.role_id === roleId);
      const schema = this.game.scenario.role_settings_schema[roleId];
      form.replaceChildren(element('h2', this.roleName(roleId)));
      const mode = this.select([['ai', 'ИИ'], ['human', 'Я сам']], draft.control_mode);
      this.settingField('Управление ролью', 'control_mode', mode, (input) => draft.control_mode = input.value);
      const money = Object.assign(element('input'), { type: 'number', min: 0, max: schema.pledged_rub_max,
        step: 1, required: true, value: draft.pledged_rub });
      this.settingField('Взнос, ₽', 'pledged_rub', money, (input) => draft.pledged_rub = input.value === '' ? null : input.valueAsNumber);
      for (const condition of schema.conditions) {
        const value = draft.conditions[condition.id];
        let field;
        if (condition.allowed) field = this.select(condition.allowed.map((option) => [option, option]), value);
        else if (condition.type === 'boolean') field = Object.assign(element('input'), { type: 'checkbox', checked: value });
        else field = Object.assign(element('input'), { type: condition.type === 'integer' ? 'number' : 'text', value,
          required: true, ...(condition.min_value == null ? {} : { min: condition.min_value }),
          ...(condition.max_value == null ? {} : { max: condition.max_value }) });
        this.settingField(condition.label, `conditions.${condition.id}`, field, (input) => {
          draft.conditions[condition.id] = condition.type === 'boolean' ? input.checked :
            condition.type === 'integer' ? (input.value === '' ? null : Number(input.value)) : input.value;
        });
      }
      const strategy = Object.assign(element('textarea'), { value: draft.strategy || '', maxLength: 6000 });
      this.settingField('Стратегия', 'strategy', strategy, (input) => draft.strategy = input.value.trim() || null);
    }

    settingField(text, path, field, update) {
      field.dataset.path = path;
      $('role-settings').append(this.label(text, field));
      field.oninput = () => {
        field.removeAttribute('aria-invalid');
        update(field);
        localStorage.setItem(draftKey(this.game.game_id), JSON.stringify(this.draft));
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

    async start() {
      const id = this.game.game_id;
      try {
        await api(`/${id}/settings`, 'PUT', { roles: this.draft });
      } catch (error) {
        const issue = error.field_errors?.[0];
        const role = issue?.path[0] === 'roles' && this.draft[issue.path[1]];
        if (role) {
          this.selectRole(role.role_id);
          const path = issue.path.slice(2).join('.');
          const field = Array.from($('role-settings').elements).find((item) => item.dataset.path === path);
          field?.setAttribute('aria-invalid', 'true');
          field?.focus();
          error.message = `${this.roleName(role.role_id)}: ${issue.message}`;
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
          if (event.type === 'message.created') this.append(event.payload, true);
          else this.pollRefresh = true;
        }
        this.cursor = page.next_cursor;
        if (page.has_more) delay = 0;
        else if (this.pollRefresh) {
          this.apply(await api(`/${id}`));
          this.pollRefresh = false;
        }
      } catch (error) {
        if (this.game?.game_id !== id) return;
        delay = 2000;
        if (error.code === 'EVENT_CURSOR_EXPIRED') {
          try { this.apply(await api(`/${id}`), true); } catch (refreshError) { this.handleError(refreshError); }
        } else if (error.status === 404) this.handleError(error);
      } finally {
        if (this.polling === id) this.polling = null;
        if (this.game?.game_id === id && this.game.status === 'running') this.schedulePoll(delay);
      }
    }

    roleName(id) {
      return this.game.scenario.roles.find((role) => role.id === id)?.name || id;
    }

    append(message, animate) {
      if (this.messageIds.has(message.message_id)) return;
      this.messageIds.add(message.message_id);
      const item = element('article');
      item.className = animate ? 'speech-item' : 'speech-item restored';
      const title = element('h2', this.roleName(message.role_id));
      title.className = 'speech-role';
      const text = element('p', message.content);
      text.className = 'speech-text';
      item.append(title, text);
      $('debate-feed').append(item);
      if (animate) item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    renderDebate() {
      const game = this.game;
      const actions = game.available_actions;
      const pause = game.pause_state === 'requested' ? ' · Пауза запрошена' : game.pause_state === 'paused' ? ' · Пауза' : '';
      $('phase-title').textContent = (phaseLabels[game.phase] || 'Дебаты') + pause;
      $('pause-btn').textContent = game.pause_state === 'none' ? 'ПАУЗА' : 'ПРОДОЛЖИТЬ';
      $('pause-btn').hidden = !actions.includes('pause') && !actions.includes('continue');
      $('stop-btn').hidden = !actions.includes('cancel');
      const aiRoles = game.settings.roles.filter((role) => role.control_mode === 'ai');
      $('instruction-form').hidden = !actions.includes('add_instruction') || !aiRoles.length;
      const roles = $('instruction-role');
      if (roles.options.length !== aiRoles.length) {
        roles.replaceChildren(...aiRoles.map((role) => new Option(this.roleName(role.role_id), role.role_id)));
      }
      const protocol = $('protocol-panel');
      protocol.hidden = !game.protocol;
      protocol.replaceChildren();
      if (game.protocol) this.renderProtocol(protocol);
      const form = $('manual-input');
      const pending = game.pending_input;
      form.hidden = !pending;
      if (this.inputId !== pending?.input_id) {
        form.replaceChildren();
        this.inputId = pending?.input_id;
        if (pending) {
          form.append(element('h2', this.roleName(pending.role_id)));
          if (pending.type === 'speech') {
            const field = Object.assign(element('textarea'), { name: 'content', required: true, maxLength: 6000 });
            form.append(this.label('Ваше выступление', field));
          } else {
            const field = this.select(pending.allowed_votes.map((vote) => [vote, voteLabels[vote]]), '');
            field.name = 'vote';
            field.required = true;
            form.append(this.label(`Ваш голос по протоколу №${pending.protocol_version}`, field));
          }
          form.append(element('button', 'Отправить'));
        }
      }
      for (const field of form.elements) field.disabled = !actions.includes('submit_input');
    }

    renderProtocol(container) {
      const game = this.game;
      container.append(element('h2', `Протокол №${game.protocol.version}`));
      const items = element('ul');
      for (const item of game.protocol.items) {
        const value = typeof item.value === 'boolean' ? (item.value ? 'да' : 'нет') : item.value;
        const line = element('li', value == null ? item.title : `${item.title}: ${value}`);
        if (item.funding.length) {
          const funding = element('ul');
          for (const share of item.funding) funding.append(element('li', `${this.roleName(share.role_id)}: ${formatNumber.format(share.amount_rub)} ₽`));
          line.append(funding);
        }
        items.append(line);
      }
      container.append(items);
      if (game.forecast) this.renderIndicators(container, game.forecast, 'Прогноз при принятии');
      if (game.vote_summary) this.renderVotes(container);
    }

    renderIndicators(container, projection, title) {
      container.append(element('h3', `${title} · ${projection.period_months} мес.`));
      const list = element('ul');
      for (const metric of projection.indicators) list.append(element('li', `${metric.label}: ${metric.final_value}`));
      container.append(list);
    }

    renderVotes(container) {
      const game = this.game;
      container.append(element('h3', game.protocol_status === 'accepted' ? 'Протокол принят' : 'Соглашение не достигнуто'));
      const votes = element('ul');
      for (const row of game.vote_summary.votes) votes.append(element('li', `${this.roleName(row.role_id)}: ${voteLabels[row.vote]}`));
      container.append(votes);
    }

    renderResult() {
      const game = this.game;
      const view = $('final-text-content');
      view.replaceChildren();
      $('retry-result').hidden = !game.available_actions.includes('retry_result');
      $('final-photo').hidden = !game.result?.image_url;
      if (game.result?.image_url) $('consequence-photo').src = game.result.image_url;
      else $('consequence-photo').removeAttribute('src');
      $('result-title').textContent = { completed: 'РЕЗУЛЬТАТ', cancelled: 'ИГРА ОТМЕНЕНА', failed: 'ИГРА ПРЕРВАНА' }[game.status];
      if (game.vote_summary) this.renderVotes(view);
      if (game.error) view.append(element('p', game.error.message));
      if (game.result) {
        view.append(element('h2', game.result.outcome_title));
        this.renderIndicators(view, game.result, 'Итоговые показатели');
        const herald = element('p', game.result.herald_text);
        herald.className = 'herald-text';
        view.append(herald);
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => new GameApp());
})();
