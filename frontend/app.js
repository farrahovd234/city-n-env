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
  const fundingLabels = {
    start_money: 'Первое предложение по взносу',
    comfort_money: 'Желаемый взнос',
    max_money: 'Потолок взноса',
  };
  const formatNumber = new Intl.NumberFormat('ru-RU');
  const savedGame = 'city_n_game_id';
  const draftKey = (id) => `city_n_draft_${id}`;
  const analysisKey = (id) => `city_n_analysis_v2_${id}`;
  const analysisRoleKey = (id) => `city_n_analysis_role_${id}`;
  const analysisRetryDelays = [0, 800, 2000];
  const createKey = 'city_n_create_key';
  const readableValue = (value) => (typeof value === 'number' ? formatNumber.format(value) : value);
  const guiltLabels = new Map([
    ['shared', 'Город и холдинг'],
    ['holding', 'Холдинг'],
    ['city', 'Город'],
  ]);
  const outcomeIdByTitle = new Map([
    ['Открытая река', 'open_river'],
    ['Чистая вода, закрытые данные', 'closed_data'],
    ['Компромисс', 'compromise'],
    ['Решили без жителей', 'without_residents'],
    ['Долгострой', 'dolgostroy'],
    ['Недострой', 'nedostroy'],
    ['Каждый сам за себя', 'each_for_self'],
    ['Застой', 'stagnation'],
  ]);
  const realCityCases = {
    open_river: [
      {
        city: 'Отрадный, Самарская область',
        summary: 'В рамках проекта «Оздоровление Волги» при федеральном и региональном софинансировании (>924 млн ₽) модернизировали очистные мощностью 13 тыс. м³/сут с полной биологической очисткой и УФ-обеззараживанием — объект прошёл проверки и вышел на целевые показатели.',
      },
      {
        city: 'Москва (Курьяновские и Люберецкие ОС)',
        summary: 'Масштабная реконструкция блоков очистки включила автоматические датчики качества воды в реальном времени и передачу данных в диспетчерские центры в сочетании с публичной отчётностью по снижению сбросов и запахов.',
      },
    ],
    closed_data: [
      {
        city: 'Нижнекамск, Татарстан',
        summary: 'Крупные предприятия промузла внедряют автоматические датчики контроля по закону об охране окружающей среды, однако сырые показатели передаются преимущественно в ведомственный контур Росприроднадзора, из-за чего у жителей сохраняется запрос на открытый доступ и свои замеры.',
      },
      {
        city: 'Липецк',
        summary: 'При модернизации производств и ведомственном контроле отсутствие простого «прямого эфира» с показаниями источников подталкивает местные НКО требовать открытых витрин данных и вести параллельный общественный мониторинг.',
      },
    ],
    compromise: [
      {
        city: 'Череповец, Вологодская область',
        summary: 'Город и крупнейшие предприятия поэтапно договорились о программах модернизации и постах мониторинга на границах санитарно-защитных зон — ценой взаимных уступок по срокам и объёму открываемых для жителей данных.',
      },
      {
        city: 'Ревда, Свердловская область (запуск 2025 года)',
        summary: 'После многолетних судов и перераспределения обязательств между муниципальным, областным водоканалами и подрядчиками новые очистные на 20 тыс. м³/сут удалось довести до тестового пуска через серию хозяйственных компромиссов.',
      },
    ],
    without_residents: [
      {
        city: 'Копейск, Челябинская область',
        summary: 'Предложенный проект реконструкции очистных вызвал протесты горожан и активистов «Народного фронта»: он предусматривал очистку лишь от 6 из 12 видов загрязнений и ставил под угрозу озеро Курлады. Конфликт перешёл в обращения к прокуратуре с требованием пересмотра проекта.',
      },
      {
        city: 'Региональные публичные слушания по сбросам',
        summary: 'В ряде промышленных городов утверждение схем водоотведения без реального согласования с жителями и эко-НКО приводит к политизации темы, жалобам в надзорные органы и многолетнему противостоянию.',
      },
    ],
    dolgostroy: [
      {
        city: 'Ревда, Свердловская область (бассейн р. Чусовой)',
        summary: 'Планы по обновлению изношенных на 70–100% очистных тянулись с 2009 года до тестового запуска осенью 2025-го, сопровождаясь сменой подрядчиков, судебными исками между водоканалами и усталостью горожан от затянувшегося ожидания.',
      },
      {
        city: 'Города Черноморского побережья (Геленджик, Сочи)',
        summary: 'Срывы и переносы сроков модернизации коллекторов и очистных в пиковые сезоны неоднократно оборачивались авариями, графиками подачи и экстренным подвозом воды автоцистернами, вызывая волну жалоб жителей.',
      },
    ],
    nedostroy: [
      {
        city: 'Волгоград (остров Голодный)',
        summary: 'Реконструкция ключевых сооружений биологической очистки столкнулась со срывами сроков подрядчиками, технологическими недоделками и проверками контролирующих ведомств, надолго задержав полноценный ввод узла.',
      },
      {
        city: 'Объекты Поволжья в нацпроекте «Экология»',
        summary: 'Проверки Счётной палаты и Госдумы фиксировали случаи, когда средства на очистные распределялись и частично осваивались, но из-за ошибок проектирования и нехватки пусконаладки станции годами не выходили на нормативную очистку.',
      },
    ],
    each_for_self: [
      {
        city: 'Липецк и Нижнекамск (гражданский мониторинг)',
        summary: 'Когда общего соглашения о прозрачности нет, эко-активисты и НКО самостоятельно разворачивают сети народного мониторинга и независимые замеры, а город и заводы точечно закрывают отдельные локальные проблемы.',
      },
      {
        city: 'Муниципалитеты с аварийным подвозом воды',
        summary: 'При замороженной общей реконструкции местные власти вынуждены самостоятельно организовывать подвоз питьевой воды автоцистернами в отдельные районы, пока спор о финансировании стройки остаётся без решения.',
      },
    ],
    stagnation: [
      {
        city: 'Проблемные узлы Нижегородской и Самарской областей',
        summary: 'При затянутых спорах, ошибках в проектах и отсутствии единого контроля обновление ряда очистных фактически встало на паузу, а неочищенные или полуочищенные стоки продолжили поступать в водоёмы при нарастающем недовольстве населения.',
      },
      {
        city: 'Копейск (узел у озера Курлады)',
        summary: 'Противостояние вокруг несогласованного проекта реконструкции привело к остановке прежних решений и длительному разбирательству сторон без реального запуска обновлённых сооружений.',
      },
    ],
  };

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
      findings: report.message_ids.flatMap((id) => (byMessage.has(id) ? [byMessage.get(id)] : [])),
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

  function validQuestionValue(question, value) {
    const bounds = question.number_range;
    return bounds
      ? Number.isInteger(value) && value >= bounds.minimum && value <= bounds.maximum
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
      this.demoMode = false;
      this.hasHydrated = false;
      this.entryAnimations = new WeakMap();
      this.mockTimer = null;
      this.mockScript = [];
      this.mockIndex = 0;

      window.addEventListener('hashchange', () => this.route());
      document.querySelector('.skip-link').onclick = (event) => {
        event.preventDefault();
        $('main-info-col').focus();
      };
      $('exit-btn').onclick = () => this.navigate('start');
      $('demo-start').onclick = (event) => { event.preventDefault(); this.startDemo(); };
      $('demo-skip').onclick = () => this.finishMockDebate();
      $('role-settings').onsubmit = (event) => {
        event.preventDefault();
        const button = $('submit-settings-btn');
        void this.act(async () => {
          button.setAttribute('aria-busy', 'true');
          button.textContent = 'ЗАПУСКАЕМ…';
          try {
            await this.start();
          } finally {
            button.textContent = 'ГОТОВО';
            button.removeAttribute('aria-busy');
          }
        });
      };
      const autoDialog = $('auto-settings-dialog');
      autoDialog.addEventListener('close', () => {
        const targetRole = this.pendingAutoRole || this.selectedRole;
        this.pendingAutoRole = null;
        if (autoDialog.returnValue === 'confirm' && this.currentScreen === 'settings') {
          void this.fillDefaults(targetRole);
        }
      });
      $('latest-speech').onclick = () => {
        const item = this.latestSpeech();
        item?.focus({ preventScroll: true });
        this.scrollToSpeech(item);
      };
      $('next-role').onclick = () => {
        const index = this.roles.findIndex((role) => role.id === this.selectedRole);
        if (index < 0 || index + 1 >= this.roles.length) return;
        this.selectRole(this.roles[index + 1].id);
        this.saveDraft();
        $('main-info-col').scrollTop = 0;
        $('questionnaire-title').focus();
      };
      $('manual-input').onsubmit = (event) => {
        event.preventDefault();
        const pending = this.game?.pending_input;
        if (!pending || pending.input_id !== this.inputId) return;
        const data = new FormData(event.currentTarget);
        const value = pending.type === 'speech'
          ? { type: 'speech', content: data.get('content') }
          : { type: 'vote', vote: data.get('vote') };
        void this.act(() => this.command(`/inputs/${pending.input_id}`, value));
      };
      $('pause-btn').onclick = () => this.demoMode ? this.toggleMockPause() : this.act(() => this.command(this.game.pause_state === 'none' ? '/pause' : '/continue'));
      $('stop-btn').onclick = () => this.demoMode ? this.cancelMockDebate() : this.act(() => this.command('/cancel'));
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
      this.bindAutoHideScrollbars();
      void this.restore();
    }

    startDemo() {
      // Keep any real, server-backed game ID intact while resetting the visible demo UI.
      this.demoMode = true;
      this.clear();
      this.demoMode = true;
      const roles = [
        { id: 'city_administration', name: 'Администрация города', interest: 'Сохранить управляемость бюджета и обеспечить жителей питьевой водой на время реконструкции.' },
        { id: 'industrial_complex', name: 'Промкомплекс', interest: 'Избежать остановки градообразующего предприятия и распределить финансовую нагрузку.' },
        { id: 'region', name: 'Регион', interest: 'Согласовать софинансирование и добиться исполнимого графика работ.' },
        { id: 'residents', name: 'Жители', interest: 'Получить гарантии чистой воды, прозрачные сроки и независимый контроль.' },
        { id: 'eco_ngo', name: 'Эко-НКО', interest: 'Добиться открытых данных мониторинга и проверяемых экологических показателей.' },
      ];
      const seed = {
        city_administration: { start_money: 5, comfort_money: 8, max_money: 10, position: 'conditional', strategy: 'Согласиться на взнос при наличии графика работ и гарантированного подвоза воды.' },
        industrial_complex: { start_money: 90, comfort_money: 120, max_money: 150, position: 'conditional', strategy: 'Предложить поэтапное финансирование в обмен на реалистичный график и отсутствие полной остановки производства.' },
        region: { start_money: 45, comfort_money: 65, max_money: 90, position: 'support', strategy: 'Закрыть остаток сметы при подтверждении вкладов города и предприятия.' },
        residents: { start_money: 0, comfort_money: 0, max_money: 0, position: 'support', strategy: 'Поддержать проект только при публикации сроков, замеров и плана водоснабжения.' },
        eco_ngo: { start_money: 0, comfort_money: 0, max_money: 0, position: 'conditional', strategy: 'Поддержать соглашение при независимом мониторинге и открытом доступе к показаниям датчиков.' },
      };
      const limits = { city_administration: 30, industrial_complex: 180, region: 90, residents: 0, eco_ngo: 0 };
      const questionnaires = Object.fromEntries(roles.map((role) => [role.id, {
        fields: [
          { id: 'start_money', label: 'Первое предложение по взносу', required: true, number_range: { minimum: 0, maximum: limits[role.id], unit: 'млн ₽' }, options: [] },
          { id: 'comfort_money', label: 'Желаемый взнос', required: true, number_range: { minimum: 0, maximum: limits[role.id], unit: 'млн ₽' }, options: [] },
          { id: 'max_money', label: 'Потолок взноса', required: true, number_range: { minimum: 0, maximum: limits[role.id], unit: 'млн ₽' }, options: [] },
          { id: 'position', label: 'Позиция в переговорах', required: true, options: [
            { value: 'support', label: 'Поддержать соглашение' },
            { value: 'conditional', label: 'Поддержать при условиях' },
            { value: 'oppose', label: 'Выступить против' },
          ] },
          { id: 'strategy', label: 'Стратегия и дополнительные условия', required: false, options: [], hint: 'Коротко опишите приоритеты стороны и условия компромисса.' },
        ],
      }]));
      const gameId = `demo-city-${Date.now()}`;
      const snapshot = {
        game_id: gameId,
        last_event_id: 0,
        status: 'draft',
        phase: 'positions',
        pause_state: 'none',
        current_role_id: null,
        pending_input: null,
        available_actions: [],
        messages: [],
        scenario: {
          roles,
          questionnaires,
          role_settings_schema: Object.fromEntries(roles.map((role) => [role.id, { pledged_rub_max: limits[role.id] * 1000000 }])),
        },
        settings: {
          setup_mode: 'manual',
          roles: roles.map((role) => ({ role_id: role.id, control_mode: 'ai', answers: { ...seed[role.id] } })),
        },
        protocol: null,
        forecast: null,
        vote_summary: null,
        protocol_status: null,
        result: null,
      };
      this.mockSeed = seed;
      this.mockRoles = roles;
      this.mockScript = [
        { role_id: 'city_administration', phase: 'positions', content: 'Город готов выделить до 10 млн ₽, но только при включении подвоза питьевой воды и поэтапном графике реконструкции.' },
        { role_id: 'industrial_complex', phase: 'positions', content: 'Предприятие не может одномоментно принять на себя всю смету. Предлагаем начать с 90 млн ₽ и закрепить дальнейшие платежи за контрольными точками.' },
        { role_id: 'residents', phase: 'positions', content: 'Для жителей важны не только суммы. Нужны понятные сроки, регулярные замеры качества воды и публичный отчёт о каждом этапе.' },
        { role_id: 'eco_ngo', phase: 'negotiation', content: 'Мы готовы организовать независимый мониторинг. Показания датчиков и результаты лабораторных проб должны публиковаться в открытом доступе.' },
        { role_id: 'region', phase: 'negotiation', content: 'Регион может увеличить софинансирование до 65 млн ₽ при подтверждении вкладов остальных участников и едином календарном плане.' },
        { role_id: 'industrial_complex', phase: 'amendments', content: 'Согласны увеличить вклад до 120 млн ₽. Просим зафиксировать поэтапный ввод объектов, чтобы не останавливать производство.' },
        { role_id: 'city_administration', phase: 'amendments', content: 'Город подтверждает 10 млн ₽ и берёт на себя организацию подвоза воды. Отчёт о выполнении графика будет ежеквартальным.' },
        { role_id: 'residents', phase: 'voting', content: 'При независимом контроле, открытых данных и гарантиях подвоза воды жители поддерживают предложенный протокол.' },
      ];
      $('demo-badge').hidden = false;
      this.updateHeader('settings');
      $('demo-progress').hidden = true;
      $('demo-meter').value = 0;
      $('demo-progress-count').textContent = `0 / ${this.mockScript.length}`;
      history.replaceState(null, '', '#settings');
      this.apply(snapshot, true);
      $('main-info-col').scrollTop = 0;
    }

    mockDefaults(roleId) {
      return { ...(this.mockSeed?.[roleId] || {}) };
    }

    startMockDebate() {
      clearTimeout(this.mockTimer);
      this.finishSpeechReveal();
      this.messages.clear();
      this.rounds.clear();
      $('debate-feed').replaceChildren();
      $('empty-journal').hidden = false;
      this.mockIndex = 0;
      this.game.status = 'running';
      this.game.phase = 'positions';
      this.game.pause_state = 'none';
      this.game.current_role_id = this.mockScript[0]?.role_id || null;
      this.game.pending_input = null;
      this.game.available_actions = ['pause', 'cancel'];
      this.game.messages = [];
      this.game.settings.setup_mode = 'automatic';
      this.game.settings.roles = this.roles.map((role) => ({ role_id: role.id, control_mode: 'ai' }));
      this.game.result = null;
      this.game.protocol = null;
      this.game.forecast = null;
      this.game.vote_summary = null;
      this.game.last_event_id += 1;
      $('demo-progress').hidden = false;
      $('demo-meter').max = this.mockScript.length;
      $('demo-meter').value = 0;
      $('demo-progress-count').textContent = `0 / ${this.mockScript.length}`;
      this.navigate('debate');
      this.renderDebate();
      this.advanceMockDebate();
    }

    advanceMockDebate() {
      if (!this.demoMode || this.game?.status !== 'running' || this.game.pause_state === 'paused') return;
      const entry = this.mockScript[this.mockIndex];
      if (!entry) {
        this.finishMockDebate();
        return;
      }
      this.game.phase = entry.phase;
      this.game.current_role_id = entry.role_id;
      const message = {
        message_id: `demo-message-${this.mockIndex + 1}`,
        role_id: entry.role_id,
        phase: entry.phase,
        content: entry.content,
        skipped: false,
      };
      this.game.messages.push(message);
      this.game.last_event_id += 1;
      this.append(message, { animationDelay: 40, reveal: true, follow: true });
      this.mockIndex += 1;
      $('demo-meter').value = this.mockIndex;
      $('demo-progress-count').textContent = `${this.mockIndex} / ${this.mockScript.length}`;
      this.renderDebate();
      this.mockTimer = setTimeout(() => this.advanceMockDebate(), 1650);
    }

    toggleMockPause() {
      if (!this.demoMode || this.game?.status !== 'running') return;
      if (this.game.pause_state === 'paused') {
        this.game.pause_state = 'none';
        this.game.available_actions = ['pause', 'cancel'];
        this.renderDebate();
        this.advanceMockDebate();
      } else {
        clearTimeout(this.mockTimer);
        this.finishSpeechReveal();
        this.game.pause_state = 'paused';
        this.game.available_actions = ['continue', 'cancel'];
        this.renderDebate();
      }
    }

    cancelMockDebate() {
      if (!this.demoMode || !this.game) return;
      clearTimeout(this.mockTimer);
      this.finishSpeechReveal();
      this.game.status = 'cancelled';
      this.game.current_role_id = null;
      this.game.available_actions = [];
      this.game.last_event_id += 1;
      this.apply(this.game);
      this.navigate('final');
      $('demo-progress').hidden = true;
    }

    finishMockDebate() {
      if (!this.demoMode || !this.game || this.game.status === 'completed') return;
      clearTimeout(this.mockTimer);
      this.finishSpeechReveal();
      this.mockIndex = this.mockScript.length;
      for (let index = this.game.messages.length; index < this.mockScript.length; index += 1) {
        const entry = this.mockScript[index];
        const message = {
          message_id: `demo-message-${index + 1}`,
          role_id: entry.role_id,
          phase: entry.phase,
          content: entry.content,
          skipped: false,
        };
        this.game.messages.push(message);
        this.game.last_event_id += 1;
        this.append(message, { animationDelay: 30, reveal: false });
      }
      this.game.status = 'completed';
      this.game.phase = 'calculating_result';
      this.game.pause_state = 'none';
      this.game.current_role_id = null;
      this.game.available_actions = [];
      this.game.protocol_status = 'accepted';
      this.game.protocol = {
        version: 1,
        items: [
          { item_id: 'guilt', title: 'Ответственность за аварию', value: 'shared', funding: [] },
          { item_id: 'schedule', title: 'График реконструкции', value: 'Поэтапный ввод в течение 3 лет', funding: [] },
          { item_id: 'monitoring', title: 'Экологический контроль', value: 'Независимые замеры и открытая публикация данных', funding: [] },
          { item_id: 'water', title: 'Подвоз питьевой воды', value: 'На период работ за счёт города', funding: [] },
          { item_id: 'contribution', title: 'Распределение взносов', value: null, funding: [
            { role_id: 'city_administration', amount_rub: 10000000 },
            { role_id: 'industrial_complex', amount_rub: 120000000 },
            { role_id: 'region', amount_rub: 65000000 },
          ] },
        ],
      };
      this.game.forecast = null;
      this.game.vote_summary = {
        for: 5, against: 0, abstain: 0,
        votes: this.roles.map((role) => ({ role_id: role.id, vote: 'for' })),
      };
      this.game.result = {
        outcome_title: 'Компромисс',
        image_url: 'assets/demo-river.jpg',
        period_months: 120,
        herald_text: 'Стороны согласовали поэтапную реконструкцию очистных сооружений и распределили финансирование. Город организовал подвоз питьевой воды на время работ, а предприятие и регион закрепили свои взносы в общем протоколе.\n\nНезависимые замеры качества воды публикуются в открытом доступе. Темпы восстановления реки остаются неоднородными, однако регулярный контроль и единый график позволили снизить число аварийных сбросов и вернуть жителям возможность проверять исполнение договорённостей.\n\nЧерез десять лет очистные работают стабильнее, набережная постепенно возвращается к городской жизни, а доверие к переговорам сохраняется благодаря публичной отчётности.',
        indicators: [
          { label: 'Состояние реки', final_value: 'Улучшение' },
          { label: 'Работа очистных', final_value: 'Стабильная, поэтапная модернизация' },
          { label: 'Открытость данных', final_value: 'Регулярные публичные замеры' },
          { label: 'Доверие жителей', final_value: 'Постепенно восстановлено' },
        ],
      };
      this.game.last_event_id += 1;
      this.apply(this.game);
      this.navigate('final');
      $('demo-progress').hidden = true;
    }

    bindAutoHideScrollbars() {
      const timers = new WeakMap();
      const show = (target, delay = 900) => {
        target.classList.add('is-scrolling');
        clearTimeout(timers.get(target));
        timers.set(target, setTimeout(() => target.classList.remove('is-scrolling'), delay));
      };
      for (const container of [$('main-info-col'), ...document.querySelectorAll('.menu-grid')]) {
        container.addEventListener('scroll', () => show(container), { passive: true });
        container.addEventListener('mousemove', (event) => {
          const rect = container.getBoundingClientRect();
          if (rect.right - event.clientX <= 18 && container.scrollHeight > container.clientHeight) {
            show(container, 1200);
          }
        }, { passive: true });
      }
      window.addEventListener('scroll', () => {
        show(document.documentElement);
        show(document.body);
      }, { passive: true });
    }

    get roles() {
      return this.game.scenario.roles;
    }

    roleName(id) {
      return this.roles.find((role) => role.id === id)?.name || id;
    }

    notice(id, message = '') {
      const node = $(id);
      if (node.textContent !== message) node.textContent = message;
      node.hidden = !message;
      if (id === 'setup-mode' || id === 'setup-auto-error') {
        const card = $('setup-card');
        if (card) card.hidden = $('setup-mode').hidden && $('setup-auto-error').hidden;
      }
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
      for (const id of ['submit-settings-btn', 'next-role']) $(id).disabled = locked;
      for (const btn of $('roles-nav').querySelectorAll('.role-auto-btn')) btn.disabled = locked;
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
      const activeId = this.game?.game_id;
      const id = activeId || (!this.demoMode ? localStorage.getItem(savedGame) : null);
      const disposableId = id && (!this.demoMode || id.startsWith('demo-city-')) ? id : null;
      if (disposableId) localStorage.removeItem(draftKey(disposableId));
      if (disposableId) {
        try {
          sessionStorage.removeItem(analysisKey(disposableId));
          sessionStorage.removeItem(analysisRoleKey(disposableId));
        } catch { /* Analysis can run with storage disabled. */ }
      }
      if (!this.demoMode) localStorage.removeItem(savedGame);
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
      $('analysis-roles-nav').replaceChildren();
      $('analysis-summary').replaceChildren();
      $('analysis-preview-quotes').replaceChildren();
      $('analysis-result').replaceChildren();
      $('instruction-role').replaceChildren();
      $('instruction-text').value = '';
      $('debate-feed').replaceChildren();
      $('protocol-panel').replaceChildren();
      $('live-votes').replaceChildren();
      $('final-votes').replaceChildren();
      $('final-indicators').replaceChildren();
      $('final-cases').replaceChildren();
      $('final-cases').hidden = true;
      $('final-protocol-body').replaceChildren();
      $('final-text-content').replaceChildren();
      $('consequence-photo').removeAttribute('src');
      $('journal-archive').open = false;
      $('final-protocol').open = false;
      $('live-journal').prepend($('journal-content'));
      this.notice('game-error');
      this.notice('setup-mode');
      this.notice('setup-auto-error');
      $('demo-badge').hidden = true;
      this.updateHeader(this.currentScreen || 'start');
      $('demo-progress').hidden = true;
      clearTimeout(this.mockTimer);
      this.demoMode = false;
    }

    async restore() {
      this.restoring = true;
      try {
        const gameId = localStorage.getItem(savedGame);
        if (gameId) {
          this.apply(await api(`/${gameId}`), true);
        } else {
          this.restoring = false;
          this.route();
        }
      } catch (error) {
        this.handleError(error);
      } finally {
        this.restoring = false;
        this.hasHydrated = true;
        document.documentElement.classList.add('app-ready');
        this.updateHeader(this.currentScreen || 'start');
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
      const previousScreen = this.currentScreen;
      const changed = previousScreen !== name || previous !== page;
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

      document.querySelector('.screen-frame').dataset.currentScreen = name;
      document.documentElement.dataset.screen = name;
      for (const view of document.querySelectorAll('.screen-view')) {
        const match = view.dataset.screenView === name;
        view.hidden = !match;
        view.classList.toggle('active', match);
        if (match && changed && this.hasHydrated && !this.restoring) this.animateEntry(view);
        else if (!match) {
          this.entryAnimations.delete(view);
          view.classList.remove('view-entering');
        }
      }
      for (const menu of document.querySelectorAll('.menu-view')) {
        const match = menu.dataset.menuView === name;
        menu.hidden = !match;
        menu.classList.toggle('active', match);
        if (match && changed && this.hasHydrated && !this.restoring) this.animateEntry(menu);
        else if (!match) {
          this.entryAnimations.delete(menu);
          menu.classList.remove('view-entering');
        }
      }
      this.updateHeader(name);

      const video = $('instruction-video');
      if (name === 'instruction') video.play().catch(() => {});
      else video.pause();

      const stage = this.game ? this.gameScreen() : 'settings';
      if (name === 'start') {
        const link = $('start-link');
        link.href = `#${stage}`;
        const labels = {
          settings: 'ПРОДОЛЖИТЬ НАСТРОЙКУ',
          debate: 'ВЕРНУТЬСЯ К ДЕБАТАМ',
          final: 'К РЕЗУЛЬТАТУ',
        };
        link.textContent = this.game ? labels[stage] : 'ИГРАТЬ';
      }
      if (name === 'instruction') {
        const link = $('rules-return');
        link.href = `#${stage}`;
        const labels = {
          settings: 'К АНКЕТАМ',
          debate: 'К ДЕБАТАМ',
          final: 'К ИГРЕ',
        };
        link.textContent = this.game ? labels[stage] : 'ИГРАТЬ';
      }
      if (name === 'assistant') this.resumeAnalysis();

      if (changed) {
        $('main-info-col').scrollTop = 0;
        window.scrollTo(0, 0);
        if (previous) {
          const heading = document.querySelector(`[data-menu-view="${name}"] h1`);
          if (heading) {
            heading.tabIndex = -1;
            heading.focus({ preventScroll: true });
          }
        }
      }
    }

    updateHeader(name) {
      const labels = {
        start: 'ИНТЕРАКТИВНЫЙ СЦЕНАРИЙ',
        instruction: 'ПРАВИЛА И КОНТЕКСТ',
        settings: 'НАСТРОЙКА ПОЗИЦИЙ',
        debate: 'ПЕРЕГОВОРЫ В РЕАЛЬНОМ ВРЕМЕНИ',
        final: 'ПРОГНОЗ ПОСЛЕДСТВИЙ',
        assistant: 'АНАЛИЗ ПЕРЕГОВОРОВ',
      };
      const stage = $('header-stage');
      if (stage) stage.textContent = labels[name] || labels.start;
      const header = document.querySelector('.site-header');
      if (header) {
        header.dataset.screen = name;
        header.dataset.mode = this.demoMode ? 'demo' : (this.game ? 'session' : 'intro');
      }
    }

    animateEntry(node) {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      node.classList.remove('view-entering');
      const token = {};
      this.entryAnimations.set(node, token);
      const finish = (event) => {
        if (event && event.target !== node) return;
        if (this.entryAnimations.get(node) !== token) {
          node.removeEventListener('animationend', finish);
          return;
        }
        this.entryAnimations.delete(node);
        node.classList.remove('view-entering');
        node.removeEventListener('animationend', finish);
      };
      node.addEventListener('animationend', finish);
      requestAnimationFrame(() => {
        if (this.entryAnimations.get(node) === token && node.isConnected && !node.hidden) {
          node.classList.add('view-entering');
        } else {
          finish();
        }
      });
      window.setTimeout(() => finish(), 1100);
    }

    apply(snapshot, recover = false) {
      if (!recover && this.game?.game_id !== snapshot.game_id) return;
      if (!recover && snapshot.last_event_id < this.game.last_event_id) return;
      const previous = this.game;
      this.game = snapshot;
      if (!this.demoMode) localStorage.setItem(savedGame, snapshot.game_id);
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
      this.notice('setup-auto-error');
      this.notice('setup-mode');
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
        this.draft = Array.isArray(savedDraft)
          ? savedDraft
          : settings.roles.map(({ spent_on_conditions_rub, ...role }) => role);
      }
      const selected = this.roles.find(({ id }) => this.draft.selectedRole === id);
      this.selectRole(selected?.id || this.roles[0].id);
    }

    saveDraft() {
      localStorage.setItem(draftKey(this.game.game_id), JSON.stringify(this.draft));
    }

    requestDefaults(roleId = this.selectedRole) {
      const dialog = $('auto-settings-dialog');
      if (dialog.open || this.busy || this.game?.status !== 'draft') return;
      const roleAnswers = this.draft.answers[roleId] || {};
      const hasRoleAnswers = Object.keys(roleAnswers).length > 0;
      if (hasRoleAnswers) {
        this.pendingAutoRole = roleId;
        $('auto-dialog-copy').textContent = `Готовые настройки заменят текущие ответы в анкете «${this.roleName(roleId)}».`;
        dialog.returnValue = '';
        dialog.showModal();
      } else {
        void this.fillDefaults(roleId);
      }
    }

    async fillDefaults(roleId = this.selectedRole) {
      if (this.game?.status !== 'draft' || !roleId) return;
      if (this.demoMode) {
        this.draft.answers[roleId] = this.mockDefaults(roleId);
        this.draft.mode = 'manual';
        this.draft.usedDefaults = true;
        this.saveDraft();
        this.selectRole(roleId);
        this.notice('setup-mode', 'Тестовые ответы применены. Их можно изменить вручную.');
        return;
      }
      const id = this.game.game_id;
      const button = $('roles-nav').querySelector(`.role-auto-btn[data-auto-role="${roleId}"]`);
      await this.act(async () => {
        if (button) {
          button.setAttribute('aria-busy', 'true');
          button.textContent = 'ПОДГОТОВКА…';
        }
        $('setup-card').dataset.state = 'pending';
        this.notice('setup-auto-error');
        this.notice('setup-mode', 'Загружаем настройки стороны…');
        try {
          const snapshot = await api(`/${id}/settings`, 'PUT', { mode: 'automatic' });
          if (this.game?.game_id !== id) return;
          this.apply(snapshot);
          const defaults = snapshot.settings.roles.find((role) => role.role_id === roleId)?.answers;
          if (defaults) {
            this.draft.answers[roleId] = { ...defaults };
          }
          this.draft.mode = 'manual';
          this.draft.usedDefaults = true;
          this.draft.selectedRole = this.selectedRole;
          this.saveDraft();
          this.selectRole(this.selectedRole);
        } catch (error) {
          if (error.status === 404 || error.status === 409) throw error;
          this.notice('setup-auto-error', error.message || 'Повторите автонастройку.');
        } finally {
          if (button) {
            button.textContent = 'АВТОНАСТРОЙКА';
            button.removeAttribute('aria-busy');
          }
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
        for (const role of this.roles) {
          const row = element('li');
          row.dataset.game = this.game.game_id;
          const button = element('button', null, 'menu-btn role-link');
          button.type = 'button';
          button.dataset.roleId = role.id;
          const mark = element('span', '', 'role-check');
          mark.setAttribute('aria-hidden', 'true');
          const indicator = element('span', '', 'sr-only');
          button.append(element('span', role.name), mark, indicator);
          button.onclick = () => {
            this.selectRole(role.id);
            this.saveDraft();
            $('main-info-col').scrollTop = 0;
          };
          const submenu = element('div', null, 'role-submenu');
          submenu.hidden = true;
          const autoBtn = element('button', 'АВТОНАСТРОЙКА', 'menu-btn role-auto-btn');
          autoBtn.type = 'button';
          autoBtn.dataset.autoRole = role.id;
          autoBtn.onclick = () => this.requestDefaults(role.id);
          submenu.append(autoBtn);
          row.append(button, submenu);
          nav.append(row);
        }
      }
      let completed = 0;
      for (const [index, role] of this.roles.entries()) {
        const row = nav.children[index];
        const button = row.querySelector('.role-link');
        const submenu = row.querySelector('.role-submenu');
        const active = this.selectedRole === role.id;
        if (active) button.setAttribute('aria-current', 'true');
        else button.removeAttribute('aria-current');
        button.classList.toggle('active', active);
        if (submenu) submenu.hidden = !active || !this.questionnaires;
        const complete = this.questionnaires && !this.missingQuestion(role.id);
        if (complete) completed++;
        button.querySelector('.role-check').textContent = complete ? '✓' : '';
        button.lastChild.textContent = complete ? ', анкета заполнена' : '';
      }
      if (this.questionnaires) {
        const progress = $('settings-progress');
        const count = `Анкеты: ${completed} / ${this.roles.length}`;
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
      const message = failed
        ? ''
        : this.draft.mode === 'automatic'
          ? 'Настройки пяти сторон готовы. Можно запускать партию.'
          : this.draft.usedDefaults
            ? 'Автонастройка применена.'
            : '';
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
        const funding = Object.hasOwn(fundingLabels, question.id)
          || (roleId === 'city_administration' && question.id === 'water_supply');
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
      } else {
        wrapper.append(label);
      }
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
        const fraction = maximum === minimum ? 0 : (slider.valueAsNumber - minimum) / (maximum - minimum);
        slider.style.setProperty('--fill', `${fraction * 100}%`);
        slider.setAttribute('aria-valuetext', answer === undefined
          ? `Без ответа, от ${minimum} до ${maximum} ${unit}`
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
      this.settingField(form, 'Управление ролью', 'control_mode', mode, (input) => { draft.control_mode = input.value; });
      const money = Object.assign(element('input'), {
        type: 'number', min: 0, max: schema.pledged_rub_max, step: 1, required: true, value: draft.pledged_rub,
      });
      this.settingField(form, 'Взнос, ₽', 'pledged_rub', money, (input) => {
        draft.pledged_rub = input.value === '' ? null : input.valueAsNumber;
      });
      for (const condition of schema.conditions) {
        const value = draft.conditions[condition.id];
        let field;
        if (condition.allowed) {
          field = this.select(condition.allowed.map((option) => [option, conditionValue(condition.id, option)]), value);
        } else if (condition.type === 'boolean') {
          field = Object.assign(element('input'), { type: 'checkbox', checked: value });
        } else {
          field = Object.assign(element('input'), {
            type: condition.type === 'integer' ? 'number' : 'text', value, required: true,
            ...(condition.min_value == null ? {} : { min: condition.min_value }),
            ...(condition.max_value == null ? {} : { max: condition.max_value }),
          });
        }
        this.settingField(form, condition.label, `conditions.${condition.id}`, field, (input) => {
          draft.conditions[condition.id] = condition.type === 'boolean'
            ? input.checked
            : condition.type === 'integer'
              ? (input.value === '' ? null : Number(input.value))
              : input.value;
        });
      }
      const strategy = Object.assign(element('textarea'), { value: draft.strategy || '', maxLength: 6000, rows: 3 });
      this.settingField(form, 'Стратегия', 'strategy', strategy, (input) => {
        draft.strategy = input.value.trim() || null;
      });
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
      } else {
        this.notice('settings-error', message);
      }
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
          const message = bounds
            ? `Введите целое число от ${bounds.minimum} до ${bounds.maximum} ${bounds.unit}.`
            : `Ответьте на обязательные вопросы анкеты «${this.roleName(roleId)}».`;
          this.settingsError(roleId, missing.id, message);
          return;
        }
      }
      if (this.demoMode) {
        this.saveDraft();
        this.startMockDebate();
        return;
      }
      const payload = !this.questionnaires
        ? { roles: this.draft }
        : this.draft.mode === 'automatic'
          ? { mode: 'automatic' }
          : { mode: 'manual', answers: this.draft.answers };
      try {
        await api(`/${id}/settings`, 'PUT', payload);
      } catch (error) {
        const issue = error.field_errors?.[0];
        const path = issue?.path || [];
        const answersIndex = path.indexOf('answers');
        const legacyRole = path[0] === 'roles' && this.draft[path[1]]?.role_id;
        const roleId = answersIndex === -1 ? legacyRole : path[answersIndex + 1];
        if (this.roles.some(({ id: known }) => known === roleId)) {
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
        const infoCol = $('main-info-col');
        const limitBottom = Math.min(window.innerHeight, infoCol.getBoundingClientRect().bottom);
        const following = live && (!latest || latest.getBoundingClientRect().bottom <= limitBottom + 48);
        const newest = live && page.events.findLast((event) => event.type === 'message.created'
          && !this.messages.has(event.payload.message_id));
        let added = 0;
        for (const event of page.events) {
          if (event.type === 'message.created') {
            if (this.append(event.payload, {
              animationDelay: live ? Math.min(added * 65, 195) : null,
              reveal: event === newest,
              follow: following,
            })) added++;
          } else {
            this.pollRefresh = true;
          }
        }
        if (added && following) {
          this.scrollToSpeech($('current-speaker').hidden ? this.latestSpeech() : $('current-speaker'));
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
        } else if (error.status === 404) {
          this.handleError(error);
        }
      } finally {
        if (this.polling === id) this.polling = null;
        if (this.game?.game_id === id && this.game.status === 'running') this.schedulePoll(delay);
      }
    }

    latestSpeech() {
      return [...this.messages.values()].at(-1)?.item;
    }

    scrollToSpeech(item) {
      if (!item) return;
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const infoCol = $('main-info-col');
      const box = infoCol.getBoundingClientRect();
      const position = item.getBoundingClientRect();
      const topLimit = Math.max(0, box.top);
      const bottomLimit = Math.min(window.innerHeight, box.bottom);
      if (position.bottom > bottomLimit || position.top < topLimit) {
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
        round.append(element('h2', phaseLabels[phase] || 'Выступления', 'journal-round-title'));
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
      const heading = element('div', null, 'speech-heading');
      heading.append(element('h3', this.roleName(message.role_id), 'speech-role'));
      const text = element('p', publicText(message.content), 'speech-text');
      item.append(heading, text);
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
          const infoCol = $('main-info-col');
          const bottomLimit = Math.min(window.innerHeight, infoCol.getBoundingClientRect().bottom);
          const bottom = item.getBoundingClientRect().bottom;
          paragraph.textContent = content.slice(0, ends[next - 1]);
          visible = next;
          if (follow && bottom <= bottomLimit + 32 && item.getBoundingClientRect().bottom > bottomLimit) {
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
      $('archive-count').textContent = `(${count})`;
    }

    renderDebate() {
      const game = this.game;
      const actions = game.available_actions;
      const completed = game.status === 'completed';
      this.renderJournalCount();
      const pause = game.pause_state === 'requested' ? ' · Пауза запрошена' : game.pause_state === 'paused' ? ' · Пауза' : '';
      $('phase-title').textContent = completed
        ? 'Заседание завершено'
        : (phaseLabels[game.phase] || 'Подготовка участников') + pause;
      const hasCompletedResult = completed && Boolean(game.result);
      $('newspaper-action').hidden = !hasCompletedResult;
      $('debate-open-final').hidden = !hasCompletedResult;

      const speaker = $('current-speaker');
      speaker.hidden = !game.current_role_id;
      if (game.current_role_id && speaker.dataset.roleId !== game.current_role_id) {
        speaker.dataset.roleId = game.current_role_id;
        speaker.replaceChildren(element('strong', this.roleName(game.current_role_id)), element('small'));
      }
      if (game.current_role_id) {
        const caption = game.pause_state !== 'none'
          ? 'Пауза'
          : game.pending_input
            ? 'Текущий ход'
            : game.phase === 'voting'
              ? 'Голосует'
              : 'Готовит реплику';
        const status = speaker.querySelector('small');
        if (status.textContent !== caption) status.textContent = caption;
      }

      $('pause-btn').textContent = game.pause_state === 'none' ? 'ПАУЗА' : 'ПРОДОЛЖИТЬ';
      $('pause-btn').hidden = !actions.includes('pause') && !actions.includes('continue');
      $('stop-btn').hidden = !actions.includes('cancel');

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
          form.append(element('button', 'Отправить', 'action-btn-solid'));
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
            row.append(
              element('dt', this.roleName(share.role_id)),
              element('dd', `${formatNumber.format(share.amount_rub)} ₽`),
            );
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

    renderRealCases(container, result) {
      const urlMatch = result.image_url?.match(/\/([a-z0-9_]+)\.png(?:$|\?)/i)?.[1];
      const outcomeId = (urlMatch && realCityCases[urlMatch] && urlMatch)
        || outcomeIdByTitle.get(result.outcome_title);
      const cases = outcomeId ? realCityCases[outcomeId] : null;
      container.replaceChildren();
      container.hidden = !cases?.length;
      if (!cases?.length) return;
      container.append(element('h2', 'Похожие кейсы в городах России'));
      const list = element('dl', null, 'real-cases-list');
      for (const item of cases) {
        const row = element('div');
        row.append(element('dt', item.city), element('dd', item.summary));
        list.append(row);
      }
      container.append(list);
    }

    renderVotes(container) {
      const { vote_summary: summary, protocol_status: status } = this.game;
      container.hidden = !summary;
      container.replaceChildren();
      if (!summary) return;
      container.append(element('h2', 'Голосование'));
      const statusLabel = status === 'accepted'
        ? 'Протокол принят'
        : status === 'rejected'
          ? 'Соглашение не достигнуто'
          : 'Итоги голосования';
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
      $('result-title').textContent = {
        completed: 'ЧТО СТАЛО ЧЕРЕЗ 10 ЛЕТ',
        cancelled: 'ПАРТИЯ ОТМЕНЕНА',
        failed: 'ПАРТИЯ ПРЕРВАНА',
      }[game.status];
      const cancelled = game.status === 'cancelled';
      this.notice(
        'result-state-copy',
        cancelled
          ? (this.messages.size ? 'Сохранённые реплики доступны в журнале ниже.' : 'Заседание завершилось до первой реплики.')
          : '',
      );
      $('finish-game').textContent = result ? 'ЗАВЕРШИТЬ' : 'К НАЧАЛУ';
      this.notice('result-error', game.error?.message);
      $('retry-result').hidden = !game.available_actions.includes('retry_result');
      $('final-heading').hidden = !result;
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
          ? 'Город через 10 лет'
          : `Город через ${result.period_months} мес.`;
        $('final-photo').hidden = !result.image_url;
        if (result.image_url) $('consequence-photo').src = result.image_url;
        else $('consequence-photo').removeAttribute('src');
        const paragraphs = (result.herald_text || '').trim().split(/\n\s*\n/).filter(Boolean);
        $('final-text-content').replaceChildren(...paragraphs.map((paragraph) => element('p', paragraph)));
        this.renderRealCases($('final-cases'), result);
        $('final-indicators').replaceChildren();
        this.renderIndicators($('final-indicators'), result, 'Итоговые показатели');
      } else {
        $('final-photo').hidden = true;
        $('consequence-photo').removeAttribute('src');
        $('final-text-content').replaceChildren();
        $('final-cases').replaceChildren();
        $('final-cases').hidden = true;
      }
      const hasMessages = this.messages.size > 0;
      $('journal-archive').hidden = !hasMessages;
      $('open-archive-link').hidden = !hasMessages;
      $('assistant-archive-link').hidden = !hasMessages;
      this.renderJournalCount();

      $('analysis-panel').hidden = game.status !== 'completed';
      $('open-assistant').hidden = game.status !== 'completed';
      if (game.status === 'completed' && !$('analysis-role').options.length) {
        $('analysis-role').replaceChildren(...this.roles.map((role) => new Option(role.name, role.id)));
        this.renderAssistantRolesNav();
        try {
          const saved = JSON.parse(sessionStorage.getItem(analysisKey(game.game_id)) || '[]');
          for (const [roleId, report] of saved) this.analysisResults.set(roleId, report);
          const roleId = sessionStorage.getItem(analysisRoleKey(game.game_id));
          if (this.roles.some((role) => role.id === roleId)) $('analysis-role').value = roleId;
        } catch {
          this.analysisResults.clear();
        }
        this.showAnalysis();
      }
    }

    renderAssistantRolesNav() {
      const nav = $('analysis-roles-nav');
      nav.replaceChildren();
      for (const role of this.roles) {
        const row = element('li');
        const button = element('button', null, 'menu-btn role-link');
        button.type = 'button';
        button.dataset.roleId = role.id;
        const mark = element('span', '', 'role-check');
        mark.setAttribute('aria-hidden', 'true');
        button.append(element('span', role.name), mark);
        button.onclick = () => {
          if (this.analysisRequest) return;
          $('analysis-role').value = role.id;
          $('main-info-col').scrollTop = 0;
          this.resumeAnalysis();
        };
        const submenu = element('div', null, 'role-submenu');
        submenu.hidden = true;
        const analyzeBtn = element('button', 'РАЗОБРАТЬ', 'menu-btn role-auto-btn role-analyze-btn');
        analyzeBtn.type = 'button';
        analyzeBtn.dataset.analyzeRole = role.id;
        analyzeBtn.onclick = () => void this.requestAnalysis();
        submenu.append(analyzeBtn);
        row.append(button, submenu);
        nav.append(row);
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
      if (this.demoMode) {
        const messages = this.analysisMessages(roleId);
        if (!messages.length) return;
        const first = messages[0];
        const last = messages.at(-1);
        this.analysisResults.set(roleId, {
          observation: roleId === 'residents'
            ? 'Сторона обозначила общественный интерес и связала поддержку протокола с проверяемыми гарантиями. Это помогло перевести обсуждение от общих требований к конкретным условиям.'
            : 'Позиция стороны была понятной, а уступка по финансированию помогла приблизить соглашение. Сильнее всего сработала связка конкретного взноса и встречного обязательства.',
          paragraph: 'Демо-разбор реплик выбранной стороны.',
          references: [
            { message_id: first.message_id, quote: first.content },
            ...(last.message_id !== first.message_id ? [{ message_id: last.message_id, quote: last.content }] : []),
          ],
        });
        this.showAnalysis();
        $('analysis-result-title')?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
        return;
      }
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
          if (complete && document.activeElement?.classList?.contains('role-analyze-btn')) {
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
      const complete = Boolean(report && !report.missing_message_ids?.length);
      const ready = complete && !pending;
      const answers = this.game.settings.roles.find((role) => role.role_id === roleId)?.answers;
      const canReviewQuestionnaire = answers && Object.keys(answers).length > 0;
      const questionnaireOnly = canReviewQuestionnaire && (failed || !messages.length);
      const actionText = !messages.length
        ? 'НЕТ РЕПЛИК'
        : pending
          ? 'ГОТОВИМ РАЗБОР…'
          : complete
            ? 'РАЗБОР ГОТОВ'
            : failed
              ? 'РАЗБОР ЗАВЕРШЁН'
              : 'РАЗОБРАТЬ';

      $('analysis-role').disabled = Boolean(pending);

      for (const item of $('analysis-roles-nav').children) {
        const button = item.querySelector('.role-link');
        const submenu = item.querySelector('.role-submenu');
        const analyzeBtn = item.querySelector('.role-analyze-btn');
        const itemRoleId = button.dataset.roleId;
        const active = itemRoleId === roleId;
        if (active) button.setAttribute('aria-current', 'true');
        else button.removeAttribute('aria-current');
        button.classList.toggle('active', active);
        button.disabled = Boolean(pending);
        if (submenu) submenu.hidden = !active;
        if (active && analyzeBtn) {
          analyzeBtn.textContent = actionText;
          analyzeBtn.setAttribute('aria-disabled', String(Boolean(pending || complete || failed || !messages.length)));
          analyzeBtn.setAttribute('aria-busy', String(Boolean(pending)));
        }
        const itemReport = this.analysisResults.get(itemRoleId);
        const done = Boolean(itemReport && !itemReport.missing_message_ids?.length);
        button.querySelector('.role-check').textContent = done ? '✓' : '';
      }

      const status = pending?.retrying
        ? 'Помощник заново готовит недостающие оценки…'
        : pending
          ? 'Помощник читает реплики в журнале…'
          : '';
      this.notice('analysis-status', status);
      this.notice('analysis-error', failed ? 'Помощнику не удалось подготовить полный разбор.' : '');

      const summary = $('analysis-summary');
      if (summary.dataset.roleId !== roleId || !summary.firstChild) {
        summary.dataset.roleId = roleId;
        summary.replaceChildren(
          element('h2', this.roleName(roleId)),
          element('p', 'Разбор всех реплик выбранной стороны и рекомендации на следующую партию.'),
        );
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
          overview.append(element(
            'p',
            `Разобрано ${report.findings.length} из ${report.message_ids.length} реплик.`,
            'analysis-coverage',
          ));
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
      heading.append(
        element('h3', move ? `Реплика ${move.number}` : 'Ход стороны'),
        element('span', verdictLabel[finding.verdict], 'finding-verdict'),
      );
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
        const status = element(
          'p',
          review === false ? 'Не удалось загрузить рекомендации по анкете.' : 'Подбираем ответы для следующей партии…',
          'analysis-coverage',
        );
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
        next.append(
          element('dt', item.chosen === item.suggested ? 'Сохранить этот ответ' : 'В следующей партии'),
          element('dd', item.suggested),
        );
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
