/**
 * ============================================================================
 * ЭКОЛОГИЧЕСКАЯ ИГРА-СИМУЛЯТОР: ГОРОД N
 * Модуль клиентской логики и интеграции с бэкендом на FastAPI
 * ============================================================================
 */

(function () {
  'use strict';

  // ==========================================================================
  // 1. КОНФИГУРАЦИЯ И СЕРВИС ВЗАИМОДЕЙСТВИЯ С FASTAPI (API & WEBSOCKET)
  // ==========================================================================
  const API_CONFIG = {
    // Базовый адрес бэкенда (по умолчанию текущий хост или локальный FastAPI)
    baseUrl: window.API_BASE_URL || window.location.origin,
    wsUrl: window.WS_BASE_URL || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/debate`,
    endpoints: {
      session: '/api/game/session',
      role: '/api/game/role',
      debateStart: '/api/game/debate/start',
      debatePause: '/api/game/debate/pause',
      debateResume: '/api/game/debate/resume',
      debateStop: '/api/game/debate/stop',
      consequences: '/api/game/consequences'
    }
  };

  /**
   * Клиент взаимодействия с бэкендом FastAPI.
   * При недоступности сервера переключается в локальный демонстрационный режим.
   */
  class BackendService {
    constructor() {
      this.socket = null;
      this.isBackendConnected = false;
      this.gameSessionId = localStorage.getItem('simulation_session_id') || null;
    }

    /**
     * Создать или восстановить сессию игры
     */
    async initSession() {
      try {
        const response = await fetch(`${API_CONFIG.baseUrl}${API_CONFIG.endpoints.session}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: this.gameSessionId })
        });
        if (response.ok) {
          const data = await response.json();
          this.gameSessionId = data.session_id;
          localStorage.setItem('simulation_session_id', this.gameSessionId);
          this.isBackendConnected = true;
          console.log('[FastAPI] Сессия инициализирована:', this.gameSessionId);
          return data;
        }
      } catch (err) {
        console.warn('[FastAPI] Бэкенд не отвечает, работаем в локальном автономном режиме.');
        this.isBackendConnected = false;
      }
      return null;
    }

    /**
     * Отправить выбранную роль на бэкенд
     */
    async setRole(roleKey) {
      if (!this.isBackendConnected) return;
      try {
        await fetch(`${API_CONFIG.baseUrl}${API_CONFIG.endpoints.role}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: this.gameSessionId, role: roleKey })
        });
      } catch (err) {
        console.warn('[FastAPI] Ошибка отправки роли:', err);
      }
    }

    /**
     * Подключить WebSocket стрим реплик агентов
     */
    connectDebateWebSocket(onSpeechReceived, onCompleted) {
      if (!window.WebSocket) return false;

      const wsTarget = `${API_CONFIG.wsUrl}/${this.gameSessionId || 'demo'}`;
      try {
        this.socket = new WebSocket(wsTarget);

        this.socket.onopen = () => {
          console.log('[FastAPI WS] Соединение дебатов установлено:', wsTarget);
          this.isBackendConnected = true;
        };

        this.socket.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'speech' && onSpeechReceived) {
              onSpeechReceived(data.role, data.text);
            } else if (data.type === 'final' && onCompleted) {
              onCompleted(data.result);
            }
          } catch (e) {
            console.error('[FastAPI WS] Некорректный формат сообщения:', event.data);
          }
        };

        this.socket.onerror = (err) => {
          console.warn('[FastAPI WS] Ошибка вебсокета, переход на локальный сценарий дебатов.');
          this.socket = null;
        };

        this.socket.onclose = () => {
          console.log('[FastAPI WS] Соединение закрыто.');
          this.socket = null;
        };

        return true;
      } catch (e) {
        console.warn('[FastAPI WS] Не удалось открыть соединение.');
        return false;
      }
    }

    /**
     * Управление паузой на сервере
     */
    async setPause(isPaused) {
      if (!this.isBackendConnected) return;
      const endpoint = isPaused ? API_CONFIG.endpoints.debatePause : API_CONFIG.endpoints.debateResume;
      try {
        await fetch(`${API_CONFIG.baseUrl}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: this.gameSessionId })
        });
      } catch (err) {
        console.warn('[FastAPI] Ошибка управления паузой:', err);
      }
    }

    /**
     * Остановка дебатов
     */
    async stopDebate() {
      if (!this.isBackendConnected) return;
      try {
        await fetch(`${API_CONFIG.baseUrl}${API_CONFIG.endpoints.debateStop}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: this.gameSessionId })
        });
      } catch (err) {
        console.warn('[FastAPI] Ошибка остановки дебатов:', err);
      }
    }

    /**
     * Получение результатов последствий по роли
     */
    async fetchConsequences(roleKey) {
      if (!this.isBackendConnected) return null;
      try {
        const res = await fetch(`${API_CONFIG.baseUrl}${API_CONFIG.endpoints.consequences}?session_id=${this.gameSessionId}&role=${roleKey}`);
        if (res.ok) {
          return await res.json();
        }
      } catch (err) {
        console.warn('[FastAPI] Ошибка получения итогов:', err);
      }
      return null;
    }
  }

  // ==========================================================================
  // 2. ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ (АВТОНОМНЫЙ РЕЖИМ БЕЗ СЕРВЕРА)
  // ==========================================================================
  const localDebateScript = [
    {
      role: "Администрация",
      text: "Коллеги, ситуация на очистных сооружениях критическая: износ оборудования превышает 74%. Муниципальный бюджет готов выделить до 300 млн рублей на модернизацию первой очереди, но без долевого участия Холдинга и региональной субсидии мы не впишемся в экологический регламент."
    },
    {
      role: "Регион",
      text: "Министерство природных ресурсов области готово согласовать транш из нацпроекта в размере 500 млн рублей. Однако ключевое условие софинансирования — гарантия внедрения современной трёхступенчатой биоочистки с удалением азота и фосфора до конца четвёртого квартала."
    },
    {
      role: "Холдинг",
      text: "Предприятия комбината обеспечивают треть налоговых поступлений города. Мы уже инвестировали в локальные очистные цехов и не можем взять на себя более 20% общегородских расходов, если регион не предоставит льготу по налогу на имущество на период строительно-монтажных работ."
    },
    {
      role: "Эко НКО",
      text: "Каждый день промедления приводит к сбросу в реку до сорока тонн неочищенных взвесей. Мы настаиваем на установке открытых автоматических датчиков контроля на коллекторах комбината и города. Общественность не поддержит протокол без прозрачного мониторинга."
    },
    {
      role: "Жители",
      text: "В южных микрорайонах города концентрация сероводорода регулярно превышает ПДК в два раза. Мы требуем чётких сроков решения проблемы и категорически выступаем против повышения коммунальных тарифов на водоотведение для компенсации модернизации!"
    },
    {
      role: "Администрация",
      text: "Предлагаю компромисс: Холдинг финансирует поставку импортозамещающих мембранных биореакторов, регион покрывает 50% строительных затрат, а город берёт на себя благоустройство санитарно-защитной зоны и онлайн-датчики мониторинга."
    },
    {
      role: "Холдинг",
      text: "Если регион зафиксирует налоговый вычет на 5 лет, холдинг готов подписать гарантийное соглашение на закупку оборудования и закрыть вопрос промышленных стоков."
    },
    {
      role: "Эко НКО",
      text: "При условии круглосуточной публикации данных с датчиков и создания независимого наблюдательного совета мы готовы поддержать такой проект протокола."
    }
  ];

  const localOutcomes = {
    administration: {
      photo: 'assets/consequences/compromise.png',
      general: '<strong>Общегородской статус:</strong> К 2036 году проект комплексной модернизации очистных сооружений Города N успешно завершён. Концентрация загрязняющих веществ в акватории реки снизилась на 82%, возвращена способность экосистемы к естественному самоочищению. Запахи сероводорода в жилых кварталах устранены полностью.',
      role: '<strong>Судьба стороны (Администрация):</strong> Мэрия выполнила целевые показатели нацпроекта «Экология». Город избежал федеральных штрафов и бюджетного коллапса, доверие граждан к муниципальным институтам укрепилось, а индекс инвестиционной привлекательности города N поднялся на 14 пунктов.'
    },
    holding: {
      photo: 'assets/consequences/holding_paid.png',
      general: '<strong>Общегородской статус:</strong> Производственные мощности комбината интегрированы с обновлёнными очистными. Риски экологических аварий и аварийных остановок производства ликвидированы.',
      role: '<strong>Судьба стороны (Холдинг):</strong> Предприятие зафиксировало статус ответственного ESG-лидера отрасли. Полученные от региона налоговые льготы окупили инвестиции в мембранные фильтры за 6 лет, экспортная привлекательность продукции выросла.'
    },
    region: {
      photo: 'assets/consequences/city_paid.png',
      general: '<strong>Общегородской статус:</strong> Опыт совместного финансирования стал региональным модельным стандартом для других малых промышленных городов области.',
      role: '<strong>Судьба стороны (Регион):</strong> Правительство региона отчиталось о 100% выполнении показателей национального экологического проекта. Привлечены новые федеральные субсидии на модернизацию транспортной сети города N.'
    },
    ngo: {
      photo: 'assets/consequences/open_river.png',
      general: '<strong>Общегородской статус:</strong> В реку вернулись ценные виды рыб, индекс качества поверхностных вод перешёл из категории «загрязнённая» в «условно чистая». Независимые датчики передают данные в открытый доступ 24/7.',
      role: '<strong>Судьба стороны (Эко НКО):</strong> Организация закрепила за собой роль официального эксперта Общественной палаты. Кейс города N стал образцовым прецедентом мирного урегулирования эко-конфликта без судебных войн.'
    },
    citizens: {
      photo: 'assets/consequences/without_residents.png',
      general: '<strong>Общегородской статус:</strong> Качество водопроводной питьевой воды соответствует высшим стандартам. Инциденты с неприятным запахом прекратились, снизилась заболеваемость органов дыхания среди детей на 35%.',
      role: '<strong>Судьба стороны (Жители):</strong> Тарифы на водоотведение выросли лишь в пределах плановой инфляции. Инициативная группа трансформировалась в постоянный совет общественного самоуправления.'
    }
  };

  // ==========================================================================
  // 3. КОНТРОЛЛЕР ИНТЕРФЕЙСА (SPA ROUTER & UI LOGIC)
  // ==========================================================================
  class GameApp {
    constructor() {
      this.backend = new BackendService();
      this.validScreens = ['start', 'instruction', 'settings', 'debate', 'final'];
      this.selectedRole = localStorage.getItem('simulation_selected_role') || 'administration';

      // DOM элементы
      this.screenFrame = document.querySelector('.screen-frame');
      this.infoCol = document.getElementById('main-info-col');
      this.instructionVideo = document.getElementById('instruction-video');
      this.debateFeed = document.getElementById('debate-feed');
      this.pauseBtn = document.getElementById('pause-btn');
      this.rolesNav = document.getElementById('roles-nav');
      this.finalRolesNav = document.getElementById('final-roles-nav');
      this.consequencePhoto = document.getElementById('consequence-photo');
      this.generalText = document.getElementById('summary-general');
      this.roleText = document.getElementById('summary-role');
      this.exitBtn = document.getElementById('exit-btn');

      // Состояние дебатов
      this.isDebatePaused = false;
      this.localMessageIndex = 0;
      this.localDebateTimer = null;

      this.init();
    }

    init() {
      // Инициализация соединения с бэкендом
      this.backend.initSession();

      // Навешивание слушателей событий
      window.addEventListener('hashchange', () => this.handleHashChange());
      if (this.exitBtn) {
        this.exitBtn.addEventListener('click', () => this.handleExit());
      }
      if (this.pauseBtn) {
        this.pauseBtn.addEventListener('click', () => this.toggleDebatePause());
      }

      this.initRoleSelectors();
      this.handleHashChange();
    }

    /**
     * Обработка смены хэша страницы (#start, #instruction, #settings, #debate, #final)
     */
    handleHashChange() {
      const hash = window.location.hash.replace('#', '') || 'start';
      this.switchScreen(hash);
    }

    /**
     * Переключение экрана в SPA
     */
    switchScreen(screenName) {
      if (!this.validScreens.includes(screenName)) {
        screenName = 'start';
      }

      this.screenFrame.dataset.currentScreen = screenName;

      // Переключаем активную левую часть
      document.querySelectorAll('.screen-view').forEach(view => {
        view.classList.toggle('active', view.dataset.screenView === screenName);
      });

      // Переключаем активное правое меню
      document.querySelectorAll('.menu-view').forEach(view => {
        view.classList.toggle('active', view.dataset.menuView === screenName);
      });

      // Контроль воспроизведения видео инструкции
      if (this.instructionVideo) {
        if (screenName === 'instruction') {
          this.instructionVideo.currentTime = 0;
          this.instructionVideo.play().catch(() => {});
        } else {
          this.instructionVideo.pause();
        }
      }

      // Контроль дебатов
      if (screenName === 'debate') {
        this.startDebate();
      } else {
        this.pauseDebate();
      }

      // Скролл вверх при смене экрана
      if (screenName !== 'debate') {
        this.infoCol.scrollTo({ top: 0, behavior: 'instant' });
      }
    }

    /**
     * Выход из игры
     */
    handleExit() {
      if (confirm('Завершить сеанс игры?')) {
        window.close();
      }
    }

    /**
     * Инициализация переключения ролей на экранах настроек и итогов
     */
    initRoleSelectors() {
      // Настройка роли
      if (this.rolesNav) {
        this.rolesNav.querySelectorAll('.menu-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            this.rolesNav.querySelectorAll('.menu-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            this.selectedRole = btn.dataset.role;
            localStorage.setItem('simulation_selected_role', this.selectedRole);
            this.backend.setRole(this.selectedRole);
          });
        });
      }

      // Фильтр итогов по ролям
      if (this.finalRolesNav) {
        this.finalRolesNav.querySelectorAll('.menu-btn').forEach(btn => {
          btn.addEventListener('click', async () => {
            this.finalRolesNav.querySelectorAll('.menu-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const role = btn.dataset.role;
            await this.updateConsequenceView(role);
          });
        });
      }
    }

    /**
     * Обновить блок последствий для роли
     */
    async updateConsequenceView(roleKey) {
      // Сначала пробуем получить данные с бэкенда, иначе берем локальные
      const backendData = await this.backend.fetchConsequences(roleKey);
      const data = backendData || localOutcomes[roleKey];
      if (!data) return;

      if (this.consequencePhoto && data.photo) {
        this.consequencePhoto.src = data.photo;
      }
      if (this.generalText && data.general) {
        this.generalText.innerHTML = data.general;
      }
      if (this.roleText && data.role) {
        this.roleText.innerHTML = data.role;
      }
    }

    // ========================================================================
    // ДЕБАТЫ: ДОБАВЛЕНИЕ РЕПЛИК И СТРИМИНГ
    // ========================================================================

    /**
     * Добавить реплику в ленту (снизу вверх с автопрокруткой)
     */
    appendSpeech(role, text) {
      if (!this.debateFeed) return;
      const item = document.createElement('article');
      item.className = 'speech-item';
      item.innerHTML = `
        <h2 class="speech-role">${role}</h2>
        <p class="speech-text">${text}</p>
      `;
      this.debateFeed.appendChild(item);

      // Плавная прокрутка к последней реплике внизу
      setTimeout(() => {
        this.infoCol.scrollTo({
          top: this.infoCol.scrollHeight,
          behavior: 'smooth'
        });
      }, 50);
    }

    /**
     * Старт стрима дебатов (WebSocket с бэкенда или локальная симуляция)
     */
    startDebate() {
      if (this.debateFeed.children.length === 0) {
        this.localMessageIndex = 0;
        this.isDebatePaused = false;
        if (this.pauseBtn) this.pauseBtn.textContent = 'ПАУЗА';

        // Пробуем подключить WebSocket бэкенда FastAPI
        const wsStarted = this.backend.connectDebateWebSocket(
          (role, text) => this.appendSpeech(role, text),
          () => { window.location.hash = 'final'; }
        );

        // Если WebSocket не подключен, запускаем локальный таймер
        if (!wsStarted || !this.backend.isBackendConnected) {
          this.streamNextLocalSpeech();
        }
      }
    }

    /**
     * Локальная выдача реплик
     */
    streamNextLocalSpeech() {
      if (this.isDebatePaused) return;

      if (this.localMessageIndex < localDebateScript.length) {
        const item = localDebateScript[this.localMessageIndex];
        this.appendSpeech(item.role, item.text);
        this.localMessageIndex++;
        this.localDebateTimer = setTimeout(() => this.streamNextLocalSpeech(), 3500);
      } else {
        setTimeout(() => {
          window.location.hash = 'final';
        }, 5000);
      }
    }

    /**
     * Пауза
     */
    pauseDebate() {
      clearTimeout(this.localDebateTimer);
    }

    /**
     * Переключение паузы/возобновления
     */
    toggleDebatePause() {
      this.isDebatePaused = !this.isDebatePaused;
      this.backend.setPause(this.isDebatePaused);

      if (this.isDebatePaused) {
        if (this.pauseBtn) this.pauseBtn.textContent = 'ПРОДОЛЖИТЬ';
        this.pauseDebate();
      } else {
        if (this.pauseBtn) this.pauseBtn.textContent = 'ПАУЗА';
        this.streamNextLocalSpeech();
      }
    }
  }

  // ==========================================================================
  // 4. ЭКСПОРТ ДЛЯ БЭКЕНДА И ТЕСТИРОВАНИЯ
  // ==========================================================================
  document.addEventListener('DOMContentLoaded', () => {
    window.GameApp = new GameApp();

    // Глобальный интерфейс для внешних вызовов (FastAPI, отладка в консоли)
    window.FastApiSimulation = {
      pushSpeech: (role, text) => window.GameApp.appendSpeech(role, text),
      switchScreen: (screenId) => { window.location.hash = screenId; },
      setOutcome: (data) => {
        if (data.photo && window.GameApp.consequencePhoto) window.GameApp.consequencePhoto.src = data.photo;
        if (data.general && window.GameApp.generalText) window.GameApp.generalText.innerHTML = data.general;
        if (data.role && window.GameApp.roleText) window.GameApp.roleText.innerHTML = data.role;
      }
    };
  });

})();
