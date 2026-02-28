import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const API_BASE = '/api'

const tabs = [
  { id: 'overview', label: 'Обзор' },
  { id: 'stores', label: 'Магазины' },
  { id: 'profiles', label: 'Мой Налог' },
  { id: 'relay', label: 'Ретрансляция' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'events', label: 'События' },
  { id: 'queue', label: 'Очередь' },
  { id: 'receipts', label: 'Чеки' },
  { id: 'logs', label: 'Логи' },
  { id: 'maintenance', label: 'Обслуживание' },
]

const sectionHints = {
  overview: 'Общая картина по системе: события, очередь, чеки и ошибки по текущим фильтрам.',
  stores: 'Настройка магазина определяет, как читать webhook и как формировать чек/ретрансляцию.',
  profiles: 'Профили Мой Налог используются для выдачи чеков. При потере сессии задачи уходят в ожидание.',
  relay: 'Ретранслятор отправляет webhook в ваши внешние системы (CRM, бэк, BI) с опциональными изменениями.',
  telegram: 'Telegram-боты отправляют уведомления по выбранным событиям и помогают быстро отслеживать проблемы.',
  events: 'Журнал входящих webhook-событий YooKassa и статус их обработки.',
  queue: 'Очередь задач создания/отмены чеков с повторами и диагностикой ошибок.',
  receipts: 'Сформированные чеки и ссылки на них.',
  logs: 'Технические логи приложения для разбора проблем и аудита действий.',
  maintenance: 'Настройки очистки БД от старых/лишних данных, чтобы база не разрасталась мусором.',
}

const telegramEventOptions = [
  { key: 'payment_received', title: 'Платёж получен', hint: 'Получен webhook об успешной оплате или ожидании capture.' },
  { key: 'refund_received', title: 'Возврат получен', hint: 'Пришёл webhook о возврате/отмене платежа.' },
  { key: 'receipt_created', title: 'Чек создан', hint: 'Чек успешно создан в Мой Налог.' },
  { key: 'receipt_canceled', title: 'Чек отменён', hint: 'Чек успешно отменён в Мой Налог.' },
  { key: 'mytax_auth_required', title: 'Нужна переавторизация', hint: 'Авторизация в Мой Налог слетела, обработка временно остановлена.' },
  { key: 'mytax_auth_queue_waiting', title: 'Чеки в ожидании авторизации', hint: 'Задачи ушли в очередь WAITING_AUTH и ждут повторного входа.' },
  { key: 'mytax_auth_recovered', title: 'Авторизация восстановлена', hint: 'Доступ восстановлен, очередь снова обрабатывается.' },
  { key: 'task_retry_scheduled', title: 'Назначен повтор задачи', hint: 'Временная ошибка, задача будет повторена автоматически.' },
  { key: 'receipt_failed', title: 'Чек не удалось сформировать', hint: 'Превышен лимит попыток, нужна ручная проверка.' },
]

const templateVariables = [
  { key: '{{payment_id}}', hint: 'ID платежа из webhook.' },
  { key: '{{amount}}', hint: 'Сумма из поля amount_path.' },
  { key: '{{customer_name}}', hint: 'Имя клиента по customer_name_path.' },
  { key: '{{event}}', hint: 'Имя события, например payment.succeeded.' },
  { key: '{{payload.object.id}}', hint: 'Доступ к исходному payload webhook.' },
]

const emptyProfileForm = {
  name: '',
  provider: 'unofficial_api',
  inn: '',
  phone: '',
  password: '',
  device_id: '',
  access_token: '',
  refresh_token: '',
  cookie_blob: '',
}

const emptyTelegramForm = {
  store_id: '',
  name: '',
  bot_token: '',
  chat_id: '',
  topic_id: '',
  events_json: ['payment_received', 'receipt_created', 'receipt_canceled', 'mytax_auth_required'],
  include_receipt_url: true,
  is_active: true,
}

const emptyMaintenance = {
  log_retention_days: 30,
  event_retention_days: 30,
  queue_retention_days: 30,
  receipt_retention_days: 90,
  keep_last_logs: 5000,
  keep_last_events: 5000,
  keep_last_queue: 5000,
  keep_last_receipts: 5000,
  cleanup_interval_minutes: 60,
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    const text = await response.text()
    let message = text || `HTTP ${response.status}`
    try {
      const payload = text ? JSON.parse(text) : null
      if (payload?.detail) {
        if (typeof payload.detail === 'string') {
          message = payload.detail
        } else {
          message = JSON.stringify(payload.detail)
        }
      }
    } catch {
      // no-op
    }
    throw new Error(message)
  }
  return response.status === 204 ? {} : response.json()
}

function formatErrorMessage(error) {
  if (!(error instanceof Error)) return 'Неизвестная ошибка'
  const raw = (error.message || '').trim()
  if (!raw) return 'Неизвестная ошибка'
  try {
    const parsed = JSON.parse(raw)
    if (parsed?.detail && typeof parsed.detail === 'string') return parsed.detail
    if (parsed?.message && typeof parsed.message === 'string') return parsed.message
    return JSON.stringify(parsed)
  } catch {
    return raw
  }
}

function AsyncButton({ loading, idleText, loadingText, ...props }) {
  return (
    <button {...props} disabled={loading || props.disabled}>
      {loading ? loadingText : idleText}
    </button>
  )
}

function SectionHint({ text }) {
  return <div className="section-hint">{text}</div>
}

function InlineError({ message }) {
  if (!message) return null
  return <div className="inline-error">{message}</div>
}

function FloatingInput({ label, value, className = '', ...props }) {
  const hasValue = String(value ?? '').length > 0
  return (
    <label className={`floating-field ${hasValue ? 'has-value' : ''} ${className}`}>
      <input {...props} value={value} placeholder=" " />
      <span>{label}</span>
    </label>
  )
}

function FloatingSelect({ label, value, children, className = '', ...props }) {
  const hasValue = true
  return (
    <label className={`floating-field select-field ${hasValue ? 'has-value' : ''} ${className}`}>
      <select {...props} value={value}>
        {children}
      </select>
      <span>{label}</span>
    </label>
  )
}

function safeJsonParse(text, fallback) {
  try {
    return text ? JSON.parse(text) : fallback
  } catch {
    return fallback
  }
}

function getByPath(obj, path) {
  if (!path) return ''
  return String(path)
    .split('.')
    .filter(Boolean)
    .reduce((acc, key) => (acc && typeof acc === 'object' ? acc[key] : undefined), obj)
}

function renderSimpleTemplate(template, context) {
  if (!template) return ''
  return template.replace(/\{\{\s*([^}]+)\s*\}\}/g, (_, expr) => {
    const value = getByPath(context, String(expr).trim())
    if (value === undefined || value === null) return ''
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
  })
}

function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const [stores, setStores] = useState([])
  const [profiles, setProfiles] = useState([])
  const [relayTargets, setRelayTargets] = useState([])
  const [telegramChannels, setTelegramChannels] = useState([])
  const [events, setEvents] = useState([])
  const [queue, setQueue] = useState([])
  const [receipts, setReceipts] = useState([])
  const [logs, setLogs] = useState([])
  const [stats, setStats] = useState(null)

  const [selectedStoreId, setSelectedStoreId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [loading, setLoading] = useState(false)
  const [globalError, setGlobalError] = useState('')
  const [inlineErrors, setInlineErrors] = useState({})
  const [actionLoading, setActionLoading] = useState({})
  const [toast, setToast] = useState({ type: '', message: '' })

  const [editingProfileId, setEditingProfileId] = useState(null)
  const [editingStoreId, setEditingStoreId] = useState(null)
  const [editingRelayId, setEditingRelayId] = useState(null)
  const [editingTelegramId, setEditingTelegramId] = useState(null)
  const cacheRef = useRef({})
  const [lastFetchedAt, setLastFetchedAt] = useState({})

  const [phoneAuthForm, setPhoneAuthForm] = useState({
    profile_id: '',
    phone: '',
    challenge_token: '',
    code: '',
    expire_date: '',
  })

  const [logsSearch, setLogsSearch] = useState('')
  const [selectedProfileLogsId, setSelectedProfileLogsId] = useState('')
  const [profileLogs, setProfileLogs] = useState([])
  const [profileLogsLoading, setProfileLogsLoading] = useState(false)

  const [storeForm, setStoreForm] = useState({
    name: '',
    webhook_path: '',
    description_template: 'Оплата заказа {{payment_id}}',
    item_name_template: 'Услуга {{payment_id}}',
    amount_path: 'object.amount.value',
    payment_id_path: 'object.id',
    customer_name_path: 'object.metadata.customer_name',
    relay_mode: 'retry_until_200',
    relay_retry_limit: 5,
    include_receipt_url_in_relay: true,
    auto_cancel_on_refund: true,
    is_active: true,
    mytax_profile_id: null,
  })

  const [profileForm, setProfileForm] = useState(emptyProfileForm)

  const [relayForm, setRelayForm] = useState({
    store_id: '',
    name: '',
    url: '',
    method: 'POST',
    headers_json: '{}',
    payload_template: '',
    include_receipt_url: false,
    is_active: true,
  })

  const [telegramForm, setTelegramForm] = useState(emptyTelegramForm)
  const [maintenanceSettings, setMaintenanceSettings] = useState(emptyMaintenance)
  const [lastCleanupResult, setLastCleanupResult] = useState(null)

  const querySuffix = useMemo(() => {
    const params = new URLSearchParams()
    if (selectedStoreId) params.set('store_id', selectedStoreId)
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    const q = params.toString()
    return q ? `?${q}` : ''
  }, [selectedStoreId, dateFrom, dateTo])

  const logsQuerySuffix = useMemo(() => {
    const params = new URLSearchParams()
    if (selectedStoreId) params.set('store_id', selectedStoreId)
    if (logsSearch.trim()) params.set('q', logsSearch.trim())
    const q = params.toString()
    return q ? `?${q}` : ''
  }, [selectedStoreId, logsSearch])

  const setActionState = (key, value) => setActionLoading((prev) => ({ ...prev, [key]: value }))

  const setErrorFor = (key, message) => setInlineErrors((prev) => ({ ...prev, [key]: message }))

  const clearErrorFor = (key) => setInlineErrors((prev) => ({ ...prev, [key]: '' }))

  const showToast = (type, message) => {
    setToast({ type, message })
    window.setTimeout(() => setToast({ type: '', message: '' }), 3500)
  }

  const runAction = async (key, fn, successMessage = '') => {
    setActionState(key, true)
    clearErrorFor(key)
    try {
      await fn()
      if (successMessage) showToast('success', successMessage)
    } catch (err) {
      const message = formatErrorMessage(err)
      setErrorFor(key, message)
      showToast('error', message)
    } finally {
      setActionState(key, false)
    }
  }

  const fetchWithCache = async (key, fetcher, { force = false, ttlMs = 120000 } = {}) => {
    const now = Date.now()
    const entry = cacheRef.current[key]
    if (!force && entry && now - entry.ts < ttlMs) {
      return entry.data
    }
    const data = await fetcher()
    cacheRef.current[key] = { data, ts: now }
    setLastFetchedAt((prev) => ({ ...prev, [key]: now }))
    return data
  }

  const invalidateCache = (prefixes = []) => {
    const next = { ...cacheRef.current }
    Object.keys(next).forEach((key) => {
      if (prefixes.some((prefix) => key.startsWith(prefix))) {
        delete next[key]
      }
    })
    cacheRef.current = next
  }

  const loadAll = async ({ force = false } = {}) => {
    setLoading(true)
    setGlobalError('')
    try {
      const [storesRes, profilesRes, statsRes, maintenanceRes] = await Promise.all([
        fetchWithCache('stores', () => api('/stores'), { force, ttlMs: 180000 }),
        fetchWithCache('profiles', () => api('/profiles'), { force, ttlMs: 180000 }),
        fetchWithCache(`stats:${querySuffix}`, () => api(`/stats${querySuffix}`), { force, ttlMs: 30000 }),
        fetchWithCache('maintenance:settings', () => api('/maintenance/settings'), { force, ttlMs: 60000 }),
      ])

      const [relayRes, telegramRes, eventsRes, queueRes, receiptsRes, logsRes] = await Promise.all([
        activeTab === 'relay'
          ? fetchWithCache(`relay:${selectedStoreId || 'all'}`, () => api(`/relay-targets${selectedStoreId ? `?store_id=${selectedStoreId}` : ''}`), { force, ttlMs: 60000 })
          : Promise.resolve(null),
        activeTab === 'telegram'
          ? fetchWithCache(`telegram:${selectedStoreId || 'all'}`, () => api(`/telegram-channels${selectedStoreId ? `?store_id=${selectedStoreId}` : ''}`), { force, ttlMs: 60000 })
          : Promise.resolve(null),
        activeTab === 'events'
          ? fetchWithCache(`events:${querySuffix}`, () => api(`/events${querySuffix}`), { force, ttlMs: 30000 })
          : Promise.resolve(null),
        activeTab === 'queue'
          ? fetchWithCache(`queue:${selectedStoreId || 'all'}`, () => api(`/queue${selectedStoreId ? `?store_id=${selectedStoreId}` : ''}`), { force, ttlMs: 20000 })
          : Promise.resolve(null),
        activeTab === 'receipts'
          ? fetchWithCache(`receipts:${querySuffix}`, () => api(`/receipts${querySuffix}`), { force, ttlMs: 30000 })
          : Promise.resolve(null),
        activeTab === 'logs'
          ? fetchWithCache(`logs:${logsQuerySuffix}`, () => api(`/logs${logsQuerySuffix}${logsQuerySuffix ? '&' : '?'}limit=200`), { force, ttlMs: 30000 })
          : Promise.resolve(null),
      ])

      setStores(storesRes)
      setProfiles(profilesRes)
      if (relayRes) setRelayTargets(relayRes)
      if (telegramRes) setTelegramChannels(telegramRes)
      if (eventsRes) setEvents(eventsRes)
      if (queueRes) setQueue(queueRes)
      if (receiptsRes) setReceipts(receiptsRes)
      if (logsRes) setLogs(logsRes)
      setStats(statsRes)
      setMaintenanceSettings({
        log_retention_days: maintenanceRes.log_retention_days,
        event_retention_days: maintenanceRes.event_retention_days,
        queue_retention_days: maintenanceRes.queue_retention_days,
        receipt_retention_days: maintenanceRes.receipt_retention_days,
        keep_last_logs: maintenanceRes.keep_last_logs,
        keep_last_events: maintenanceRes.keep_last_events,
        keep_last_queue: maintenanceRes.keep_last_queue,
        keep_last_receipts: maintenanceRes.keep_last_receipts,
        cleanup_interval_minutes: maintenanceRes.cleanup_interval_minutes,
      })
    } catch (err) {
      setGlobalError(formatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [activeTab, querySuffix, logsQuerySuffix])

  const saveStore = async (event) => {
    event.preventDefault()
    await runAction(
      'storeForm',
      async () => {
        await api(editingStoreId ? `/stores/${editingStoreId}` : '/stores', {
          method: editingStoreId ? 'PUT' : 'POST',
          body: JSON.stringify({
            ...storeForm,
            relay_retry_limit: Number(storeForm.relay_retry_limit),
            mytax_profile_id: storeForm.mytax_profile_id ? Number(storeForm.mytax_profile_id) : null,
          }),
        })
        setStoreForm({
          name: '',
          webhook_path: '',
          description_template: 'Оплата заказа {{payment_id}}',
          item_name_template: 'Услуга {{payment_id}}',
          amount_path: 'object.amount.value',
          payment_id_path: 'object.id',
          customer_name_path: 'object.metadata.customer_name',
          relay_mode: 'retry_until_200',
          relay_retry_limit: 5,
          include_receipt_url_in_relay: true,
          auto_cancel_on_refund: true,
          is_active: true,
          mytax_profile_id: null,
        })
        setEditingStoreId(null)
        invalidateCache(['stores', 'stats:', 'relay:', 'events:', 'receipts:', 'queue:'])
        await loadAll({ force: true })
      },
      editingStoreId ? 'Магазин обновлён' : 'Магазин сохранён',
    )
  }

  const startEditStore = (store) => {
    setEditingStoreId(store.id)
    setStoreForm({
      name: store.name || '',
      webhook_path: store.webhook_path || '',
      description_template: store.description_template || 'Оплата заказа {{payment_id}}',
      item_name_template: store.item_name_template || 'Услуга {{payment_id}}',
      amount_path: store.amount_path || 'object.amount.value',
      payment_id_path: store.payment_id_path || 'object.id',
      customer_name_path: store.customer_name_path || 'object.metadata.customer_name',
      relay_mode: store.relay_mode || 'retry_until_200',
      relay_retry_limit: store.relay_retry_limit || 5,
      include_receipt_url_in_relay: Boolean(store.include_receipt_url_in_relay),
      auto_cancel_on_refund: Boolean(store.auto_cancel_on_refund),
      is_active: Boolean(store.is_active),
      mytax_profile_id: store.mytax_profile_id ?? null,
    })
  }

  const cancelStoreEdit = () => {
    setEditingStoreId(null)
    setStoreForm({
      name: '',
      webhook_path: '',
      description_template: 'Оплата заказа {{payment_id}}',
      item_name_template: 'Услуга {{payment_id}}',
      amount_path: 'object.amount.value',
      payment_id_path: 'object.id',
      customer_name_path: 'object.metadata.customer_name',
      relay_mode: 'retry_until_200',
      relay_retry_limit: 5,
      include_receipt_url_in_relay: true,
      auto_cancel_on_refund: true,
      is_active: true,
      mytax_profile_id: null,
    })
  }

  const createProfile = async (event) => {
    event.preventDefault()
    await runAction(
      'profileForm',
      async () => {
        await api(editingProfileId ? `/profiles/${editingProfileId}` : '/profiles', {
          method: editingProfileId ? 'PUT' : 'POST',
          body: JSON.stringify(profileForm),
        })
        setProfileForm(emptyProfileForm)
        setEditingProfileId(null)
        invalidateCache(['profiles', 'stats:'])
        await loadAll({ force: true })
      },
      editingProfileId ? 'Профиль обновлён' : 'Профиль сохранён',
    )
  }

  const loginProfile = async (profileId) => {
    await runAction(
      `profileLogin:${profileId}`,
      async () => {
        await api(`/profiles/${profileId}/login`, {
          method: 'POST',
          body: JSON.stringify({ force: true }),
        })
        invalidateCache(['profiles', 'stats:'])
        await loadAll({ force: true })
      },
      'Проверка авторизации выполнена',
    )
  }

  const checkProfileAuth = async (profileId) => {
    await runAction(
      `profileCheck:${profileId}`,
      async () => {
        const result = await api(`/profiles/${profileId}/auth/check`, { method: 'POST' })
        if (!result.is_authenticated) {
          throw new Error(result.message || 'Проверка авторизации неуспешна')
        }
        invalidateCache(['profiles', 'stats:'])
        await loadAll({ force: true })
      },
      'Сессия профиля активна',
    )
  }

  const startPhoneAuth = async (profile) => {
    await runAction(
      `profileSmsStart:${profile.id}`,
      async () => {
        const result = await api(`/profiles/${profile.id}/auth/phone/start`, {
          method: 'POST',
          body: JSON.stringify({ phone: profile.phone || profileForm.phone || '' }),
        })
        setPhoneAuthForm({
          profile_id: String(profile.id),
          phone: result.phone || profile.phone || '',
          challenge_token: result.challengeToken || '',
          code: '',
          expire_date: result.expireDate || '',
        })
      },
      'SMS challenge запрошен',
    )
  }

  const verifyPhoneAuth = async (event) => {
    event.preventDefault()
    if (!phoneAuthForm.profile_id) return
    await runAction(
      'profileSmsVerify',
      async () => {
        await api(`/profiles/${phoneAuthForm.profile_id}/auth/phone/verify`, {
          method: 'POST',
          body: JSON.stringify({
            phone: phoneAuthForm.phone,
            challenge_token: phoneAuthForm.challenge_token,
            code: phoneAuthForm.code,
          }),
        })
        setPhoneAuthForm({ profile_id: '', phone: '', challenge_token: '', code: '', expire_date: '' })
        invalidateCache(['profiles', 'stats:'])
        await loadAll({ force: true })
      },
      'Телефонная авторизация подтверждена',
    )
  }

  const startEditProfile = (profile) => {
    setEditingProfileId(profile.id)
    setProfileForm({
      name: profile.name || '',
      provider: profile.provider || 'unofficial_api',
      inn: profile.inn || '',
      phone: profile.phone || '',
      password: profile.password || '',
      device_id: profile.device_id || '',
      access_token: profile.access_token || '',
      refresh_token: profile.refresh_token || '',
      cookie_blob: profile.cookie_blob || '',
    })
  }

  const cancelProfileEdit = () => {
    setEditingProfileId(null)
    setProfileForm(emptyProfileForm)
  }

  const deleteProfile = async (profileId) => {
    await runAction(
      `profileDelete:${profileId}`,
      async () => {
        await api(`/profiles/${profileId}`, { method: 'DELETE' })
        if (editingProfileId === profileId) cancelProfileEdit()
        if (String(phoneAuthForm.profile_id) === String(profileId)) {
          setPhoneAuthForm({ profile_id: '', phone: '', challenge_token: '', code: '', expire_date: '' })
        }
        invalidateCache(['relay:'])
        await loadAll({ force: true })
      },
      'Профиль удалён',
    )
  }

  const loadProfileLogs = async (profileId) => {
    if (!profileId) {
      setSelectedProfileLogsId('')
      setProfileLogs([])
      return
    }
    await runAction(`profileLogs:${profileId}`, async () => {
      setProfileLogsLoading(true)
      try {
        setSelectedProfileLogsId(String(profileId))
        const data = await api(`/profiles/${profileId}/logs?limit=150`)
        setProfileLogs(Array.isArray(data) ? data : [])
      } finally {
        setProfileLogsLoading(false)
      }
    })
  }

  const createRelayTarget = async (event) => {
    event.preventDefault()
    await runAction(
      'relayForm',
      async () => {
        await api(editingRelayId ? `/relay-targets/${editingRelayId}` : '/relay-targets', {
          method: editingRelayId ? 'PUT' : 'POST',
          body: JSON.stringify({
            ...relayForm,
            store_id: Number(relayForm.store_id),
            headers_json: relayForm.headers_json ? JSON.parse(relayForm.headers_json) : {},
          }),
        })
        setRelayForm({
          store_id: relayForm.store_id,
          name: '',
          url: '',
          method: 'POST',
          headers_json: '{}',
          payload_template: '',
          include_receipt_url: false,
          is_active: true,
        })
        setEditingRelayId(null)
        invalidateCache(['relay:'])
        await loadAll({ force: true })
      },
      editingRelayId ? 'Ретранслятор обновлён' : 'Ретранслятор сохранён',
    )
  }

  const startEditRelayTarget = (target) => {
    setEditingRelayId(target.id)
    setRelayForm({
      store_id: String(target.store_id),
      name: target.name || '',
      url: target.url || '',
      method: target.method || 'POST',
      headers_json: JSON.stringify(target.headers_json || {}, null, 0),
      payload_template: target.payload_template || '',
      include_receipt_url: Boolean(target.include_receipt_url),
      is_active: Boolean(target.is_active),
    })
  }

  const cancelRelayEdit = () => {
    setEditingRelayId(null)
    setRelayForm({
      store_id: relayForm.store_id,
      name: '',
      url: '',
      method: 'POST',
      headers_json: '{}',
      payload_template: '',
      include_receipt_url: false,
      is_active: true,
    })
  }

  const toggleTelegramEvent = (eventName) => {
    setTelegramForm((prev) => {
      const current = new Set(prev.events_json)
      if (current.has(eventName)) {
        current.delete(eventName)
      } else {
        current.add(eventName)
      }
      return { ...prev, events_json: [...current] }
    })
  }

  const startEditTelegram = (channel) => {
    setEditingTelegramId(channel.id)
    setTelegramForm({
      store_id: String(channel.store_id),
      name: channel.name || '',
      bot_token: channel.bot_token || '',
      chat_id: channel.chat_id || '',
      topic_id: channel.topic_id ? String(channel.topic_id) : '',
      events_json: Array.isArray(channel.events_json) ? channel.events_json : [],
      include_receipt_url: Boolean(channel.include_receipt_url),
      is_active: Boolean(channel.is_active),
    })
  }

  const cancelTelegramEdit = () => {
    setEditingTelegramId(null)
    setTelegramForm(emptyTelegramForm)
  }

  const saveTelegramChannel = async (event) => {
    event.preventDefault()
    await runAction(
      'telegramForm',
      async () => {
        const payload = {
          ...telegramForm,
          store_id: Number(telegramForm.store_id),
          topic_id: telegramForm.topic_id ? Number(telegramForm.topic_id) : null,
          events_json: telegramForm.events_json,
        }
        await api(editingTelegramId ? `/telegram-channels/${editingTelegramId}` : '/telegram-channels', {
          method: editingTelegramId ? 'PUT' : 'POST',
          body: JSON.stringify(payload),
        })
        setTelegramForm(emptyTelegramForm)
        setEditingTelegramId(null)
        invalidateCache(['queue:', 'stats:'])
        await loadAll({ force: true })
      },
      editingTelegramId ? 'Telegram-бот обновлён' : 'Telegram-бот создан',
    )
  }

  const sendTelegramTest = async (channelId) => {
    await runAction(
      `telegramTest:${channelId}`,
      async () => {
        await api(`/telegram-channels/${channelId}/test`, {
          method: 'POST',
          body: JSON.stringify({
            text: 'Тест: канал работает. Это проверочное уведомление из панели YooKassa Auto.',
          }),
        })
      },
      'Тестовое сообщение отправлено',
    )
  }

  const retryTask = async (taskId) => {
    await runAction(
      `retryTask:${taskId}`,
      async () => {
        await api('/queue/retry', {
          method: 'POST',
          body: JSON.stringify({ task_id: taskId }),
        })
        invalidateCache(['maintenance:settings', 'logs:'])
        await loadAll({ force: true })
      },
      'Задача поставлена на повтор',
    )
  }

  const saveMaintenanceSettings = async (event) => {
    event.preventDefault()
    await runAction(
      'maintenanceSettings',
      async () => {
        await api('/maintenance/settings', {
          method: 'PUT',
          body: JSON.stringify({
            ...maintenanceSettings,
            log_retention_days: Number(maintenanceSettings.log_retention_days),
            event_retention_days: Number(maintenanceSettings.event_retention_days),
            queue_retention_days: Number(maintenanceSettings.queue_retention_days),
            receipt_retention_days: Number(maintenanceSettings.receipt_retention_days),
            keep_last_logs: Number(maintenanceSettings.keep_last_logs),
            keep_last_events: Number(maintenanceSettings.keep_last_events),
            keep_last_queue: Number(maintenanceSettings.keep_last_queue),
            keep_last_receipts: Number(maintenanceSettings.keep_last_receipts),
            cleanup_interval_minutes: Number(maintenanceSettings.cleanup_interval_minutes),
          }),
        })
      },
      'Настройки очистки сохранены',
    )
  }

  const runCleanupNow = async () => {
    await runAction(
      'maintenanceCleanup',
      async () => {
        const result = await api('/maintenance/cleanup', { method: 'POST', body: '{}' })
        setLastCleanupResult(result)
        await loadAll({ force: true })
      },
      'Очистка выполнена',
    )
  }

  const relayHeadersPreview = safeJsonParse(relayForm.headers_json, { parse_error: 'Невалидный JSON headers' })
  const relaySampleWebhook = {
    event: 'payment.succeeded',
    object: {
      id: '2b7f-0001',
      amount: { value: '1990.00', currency: 'RUB' },
      metadata: { customer_name: 'Иван' },
    },
  }
  const relaySamplePayload = {
    ...relaySampleWebhook,
    ...(relayForm.include_receipt_url
      ? {
          generated_receipt_url: 'https://lknpd.nalog.ru/check/preview',
          generated_receipt_uuid: 'preview-uuid',
        }
      : {}),
  }
  const relayTemplatePreviewRaw = relayForm.payload_template
    ? renderSimpleTemplate(relayForm.payload_template, relaySamplePayload)
    : ''
  const relayTemplatePreview = relayTemplatePreviewRaw
    ? safeJsonParse(relayTemplatePreviewRaw, { rendered_payload: relayTemplatePreviewRaw })
    : relaySamplePayload

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <h1>YooKassa Auto MyTax Relay</h1>
          <p>Авто-чек в «Мой налог», очередь, ретрансляция вебхуков, Telegram-уведомления</p>
          <p className="subtle small">Данные в сессии кэшируются до перезагрузки страницы. Последнее обновление: {lastFetchedAt.stores ? new Date(lastFetchedAt.stores).toLocaleTimeString() : 'ещё не было'}</p>
        </div>
        <AsyncButton
          onClick={() => loadAll({ force: true })}
          loading={loading}
          idleText="Обновить"
          loadingText="Обновление…"
        />
      </header>

      <section className="filters">
        <label>
          Магазин
          <select value={selectedStoreId} onChange={(e) => setSelectedStoreId(e.target.value)}>
            <option value="">Все</option>
            {stores.map((store) => (
              <option key={store.id} value={store.id}>{store.name}</option>
            ))}
          </select>
        </label>
        <label>
          С даты
          <input type="datetime-local" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label>
          По дату
          <input type="datetime-local" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
      </section>

      {globalError ? <div className="error">{globalError}</div> : null}

      <nav className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={activeTab === tab.id ? 'tab active' : 'tab'}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <SectionHint text={sectionHints[activeTab]} />

      {activeTab === 'overview' && stats && (
        <section className="grid cols-3">
          <div className="card"><h3>События</h3><strong>{stats.total_events}</strong></div>
          <div className="card"><h3>Чеки</h3><strong>{stats.total_receipts}</strong></div>
          <div className="card"><h3>Успешные задачи</h3><strong>{stats.success_tasks}</strong></div>
          <div className="card"><h3>В очереди</h3><strong>{stats.pending_tasks}</strong></div>
          <div className="card"><h3>Ожидают авторизации</h3><strong>{stats.waiting_auth_tasks}</strong></div>
          <div className="card"><h3>Ошибки</h3><strong>{stats.failed_tasks}</strong></div>
        </section>
      )}

      {activeTab === 'stores' && (
        <section className="stack">
          <form className="form" onSubmit={saveStore}>
            <h2>{editingStoreId ? 'Редактировать магазин' : 'Добавить магазин'}</h2>
            <p className="subtle">Ниже сначала простые настройки для бизнеса, а технические поля — в блоке «Продвинутые» с примерами.</p>
            <div className="grid cols-2">
              <FloatingInput label="Название магазина" value={storeForm.name} onChange={(e) => setStoreForm({ ...storeForm, name: e.target.value })} required />
              <FloatingInput label="Адрес webhook (например shop-a)" value={storeForm.webhook_path} onChange={(e) => setStoreForm({ ...storeForm, webhook_path: e.target.value })} required />

              <FloatingInput label="Описание в чеке" value={storeForm.description_template} onChange={(e) => setStoreForm({ ...storeForm, description_template: e.target.value })} />
              <FloatingSelect label="Профиль Мой Налог" value={storeForm.mytax_profile_id ?? ''} onChange={(e) => setStoreForm({ ...storeForm, mytax_profile_id: e.target.value || null })}>
                <option value="">Без профиля</option>
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>{profile.name}</option>
                ))}
              </FloatingSelect>
            </div>

            <p className="subtle">Переменные для поля «Описание в чеке»:</p>
            <div className="variables-row">
              {templateVariables.map((item) => (
                <span key={item.key} className="var-chip" title={item.hint}>{item.key}</span>
              ))}
            </div>

            <details className="advanced-box">
              <summary>Продвинутые настройки (для тех, кто хочет гибко настроить payload)</summary>
              <div className="grid cols-2 top-gap">
                <FloatingSelect label="Режим ретрансляции" value={storeForm.relay_mode} onChange={(e) => setStoreForm({ ...storeForm, relay_mode: e.target.value })}>
                  <option value="fire_and_forget">Отправить без ожидания ответа</option>
                  <option value="retry_until_200">Повторять до HTTP 200</option>
                </FloatingSelect>
                <FloatingInput label="Максимум повторов ретрансляции" type="number" min="1" value={storeForm.relay_retry_limit} onChange={(e) => setStoreForm({ ...storeForm, relay_retry_limit: e.target.value })} />

                <FloatingInput label="Путь к сумме (JSON path)" value={storeForm.amount_path} onChange={(e) => setStoreForm({ ...storeForm, amount_path: e.target.value })} />
                <FloatingInput label="Путь к ID платежа (JSON path)" value={storeForm.payment_id_path} onChange={(e) => setStoreForm({ ...storeForm, payment_id_path: e.target.value })} />
                <FloatingInput label="Путь к имени клиента (JSON path)" value={storeForm.customer_name_path} onChange={(e) => setStoreForm({ ...storeForm, customer_name_path: e.target.value })} />
              </div>
              <p className="subtle">Примеры путей: <b>object.amount.value</b>, <b>object.id</b>, <b>object.metadata.customer_name</b>.</p>
            </details>

            <label className="inline">
              <input type="checkbox" checked={storeForm.auto_cancel_on_refund} onChange={(e) => setStoreForm({ ...storeForm, auto_cancel_on_refund: e.target.checked })} />
              Авто-отмена чека при возврате
            </label>

            <InlineError message={inlineErrors.storeForm} />
            <div className="actions-row">
              <AsyncButton type="submit" loading={actionLoading.storeForm} idleText={editingStoreId ? 'Сохранить изменения' : 'Сохранить магазин'} loadingText="Сохранение…" />
              {editingStoreId ? <button type="button" onClick={cancelStoreEdit}>Отмена</button> : null}
            </div>
          </form>

          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Название</th><th>Webhook</th><th>Профиль</th><th>Режим relay</th><th>Активен</th><th>Действия</th></tr></thead>
              <tbody>
                {stores.map((store) => (
                  <tr key={store.id}>
                    <td>{store.id}</td>
                    <td>{store.name}</td>
                    <td>/webhook/{store.webhook_path}</td>
                    <td>{store.mytax_profile_id || '-'}</td>
                    <td>{store.relay_mode}</td>
                    <td>{store.is_active ? 'Да' : 'Нет'}</td>
                    <td><button onClick={() => startEditStore(store)}>Редактировать</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {activeTab === 'profiles' && (
        <section className="stack">
          <form className="form" onSubmit={createProfile}>
            <h2>{editingProfileId ? 'Редактировать профиль «Мой налог»' : 'Добавить профиль «Мой налог»'}</h2>
            <p className="subtle">Если авторизация слетит, задачи попадут в WAITING_AUTH и автоматически продолжатся после входа.</p>
            <div className="grid cols-2">
              <input placeholder="Название" value={profileForm.name} onChange={(e) => setProfileForm({ ...profileForm, name: e.target.value })} required />
              <select value={profileForm.provider} onChange={(e) => setProfileForm({ ...profileForm, provider: e.target.value })}>
                <option value="official_api">official_api</option>
                <option value="unofficial_api">unofficial_api</option>
              </select>
              <input placeholder="ИНН" value={profileForm.inn} onChange={(e) => setProfileForm({ ...profileForm, inn: e.target.value })} />
              <input placeholder="Телефон" value={profileForm.phone} onChange={(e) => setProfileForm({ ...profileForm, phone: e.target.value })} />
              <input placeholder="Пароль" value={profileForm.password} onChange={(e) => setProfileForm({ ...profileForm, password: e.target.value })} />
              <input placeholder="device_id" value={profileForm.device_id} onChange={(e) => setProfileForm({ ...profileForm, device_id: e.target.value })} />
              <input placeholder="access_token" value={profileForm.access_token} onChange={(e) => setProfileForm({ ...profileForm, access_token: e.target.value })} />
              <input placeholder="refresh_token" value={profileForm.refresh_token} onChange={(e) => setProfileForm({ ...profileForm, refresh_token: e.target.value })} />
              <input placeholder="cookie_blob" value={profileForm.cookie_blob} onChange={(e) => setProfileForm({ ...profileForm, cookie_blob: e.target.value })} />
            </div>
            <InlineError message={inlineErrors.profileForm} />
            <div className="actions-row">
              <AsyncButton type="submit" loading={actionLoading.profileForm} idleText={editingProfileId ? 'Сохранить изменения' : 'Сохранить профиль'} loadingText="Сохранение…" />
              {editingProfileId ? <button type="button" onClick={cancelProfileEdit}>Отмена</button> : null}
            </div>
          </form>

          {phoneAuthForm.profile_id ? (
            <form className="form" onSubmit={verifyPhoneAuth}>
              <h2>Подтверждение входа по телефону</h2>
              <div className="grid cols-2">
                <input placeholder="ID профиля" value={phoneAuthForm.profile_id} onChange={(e) => setPhoneAuthForm({ ...phoneAuthForm, profile_id: e.target.value })} required />
                <input placeholder="Телефон" value={phoneAuthForm.phone} onChange={(e) => setPhoneAuthForm({ ...phoneAuthForm, phone: e.target.value })} required />
                <input placeholder="challengeToken" value={phoneAuthForm.challenge_token} onChange={(e) => setPhoneAuthForm({ ...phoneAuthForm, challenge_token: e.target.value })} required />
                <input placeholder="Код из SMS" value={phoneAuthForm.code} onChange={(e) => setPhoneAuthForm({ ...phoneAuthForm, code: e.target.value })} required />
              </div>
              <p>Срок действия challenge: {phoneAuthForm.expire_date || 'неизвестно'}</p>
              <InlineError message={inlineErrors.profileSmsVerify} />
              <div className="actions-row">
                <AsyncButton type="submit" loading={actionLoading.profileSmsVerify} idleText="Подтвердить код" loadingText="Проверка…" />
                <button type="button" onClick={() => setPhoneAuthForm({ profile_id: '', phone: '', challenge_token: '', code: '', expire_date: '' })}>Отмена</button>
              </div>
            </form>
          ) : null}

          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Название</th><th>Provider</th><th>Статус</th><th>Последняя ошибка</th><th>Действия</th></tr></thead>
              <tbody>
                {profiles.map((profile) => (
                  <tr key={profile.id}>
                    <td>{profile.id}</td>
                    <td>{profile.name}</td>
                    <td>{profile.provider}</td>
                    <td>{profile.is_authenticated ? 'Авторизован' : 'Не авторизован'}</td>
                    <td>{profile.last_error || '-'}</td>
                    <td>
                      <div className="actions-row">
                        <AsyncButton onClick={() => loginProfile(profile.id)} loading={actionLoading[`profileLogin:${profile.id}`]} idleText="Войти/переавторизовать" loadingText="Проверка…" />
                        <AsyncButton onClick={() => checkProfileAuth(profile.id)} loading={actionLoading[`profileCheck:${profile.id}`]} idleText="Проверить сессию" loadingText="Проверка…" />
                        <AsyncButton onClick={() => startPhoneAuth(profile)} loading={actionLoading[`profileSmsStart:${profile.id}`]} idleText="Запросить SMS" loadingText="Отправка…" />
                        <button onClick={() => startEditProfile(profile)}>Редактировать</button>
                        <AsyncButton onClick={() => loadProfileLogs(profile.id)} loading={actionLoading[`profileLogs:${profile.id}`]} idleText="Auth-логи" loadingText="Загрузка…" />
                        <AsyncButton onClick={() => deleteProfile(profile.id)} loading={actionLoading[`profileDelete:${profile.id}`]} idleText="Удалить" loadingText="Удаление…" />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selectedProfileLogsId ? (
            <div className="table-wrap">
              <h3>Auth-логи профиля #{selectedProfileLogsId}</h3>
              {profileLogsLoading ? <p>Загрузка логов…</p> : null}
              <table>
                <thead><tr><th>ID</th><th>Level</th><th>Event</th><th>Сообщение</th><th>Context</th><th>Дата</th></tr></thead>
                <tbody>
                  {profileLogs.map((item) => (
                    <tr key={item.id}>
                      <td>{item.id}</td>
                      <td>{item.level}</td>
                      <td>{item.event}</td>
                      <td>{item.message}</td>
                      <td>{item.context ? JSON.stringify(item.context) : '-'}</td>
                      <td>{item.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      )}

      {activeTab === 'relay' && (
        <section className="stack">
          <form className="form" onSubmit={createRelayTarget}>
            <h2>{editingRelayId ? 'Редактировать ретранслятор' : 'Добавить ретранслятор'}</h2>
            <p className="subtle">
              Здесь настраивается <b>куда</b> и <b>в каком виде</b> отправлять уведомление. Сначала заполните URL и метод,
              потом при необходимости добавьте headers/шаблон.
            </p>
            <div className="grid cols-2">
              <FloatingSelect label="Магазин" value={relayForm.store_id} onChange={(e) => setRelayForm({ ...relayForm, store_id: e.target.value })} required>
                <option value="">Выбрать магазин</option>
                {stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
              </FloatingSelect>
              <FloatingInput label="Название ретранслятора" value={relayForm.name} onChange={(e) => setRelayForm({ ...relayForm, name: e.target.value })} required />
              <FloatingInput label="URL получателя" value={relayForm.url} onChange={(e) => setRelayForm({ ...relayForm, url: e.target.value })} required />
              <FloatingSelect label="HTTP метод" value={relayForm.method} onChange={(e) => setRelayForm({ ...relayForm, method: e.target.value })}>
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
                <option value="PATCH">PATCH</option>
                <option value="GET">GET</option>
                <option value="DELETE">DELETE</option>
              </FloatingSelect>
              <label className="inline">
                <input
                  type="checkbox"
                  checked={relayForm.include_receipt_url}
                  onChange={(e) => setRelayForm({ ...relayForm, include_receipt_url: e.target.checked })}
                />
                Добавлять ссылку на чек в этот ретранслятор
              </label>
              <FloatingInput label="HTTP headers (JSON)" value={relayForm.headers_json} onChange={(e) => setRelayForm({ ...relayForm, headers_json: e.target.value })} />
              <FloatingInput label="Шаблон payload (опционально)" value={relayForm.payload_template} onChange={(e) => setRelayForm({ ...relayForm, payload_template: e.target.value })} />
            </div>

            <div className="hint-block">
              <strong>Что куда писать:</strong>
              <p><b>URL получателя</b> — адрес вашего API/бота, куда уходит запрос.</p>
              <p><b>HTTP headers (JSON)</b> — доп. заголовки, например <code>{`{"Authorization":"Bearer ..."}`}</code>.</p>
              <p><b>Шаблон payload</b> — если пусто, отправляется исходный webhook (плюс ссылка на чек при включённом флажке).</p>
              <p>Пример шаблона: {`{"payment_id":"{{object.id}}","event":"{{event}}"}`}</p>
            </div>

            <details className="advanced-box" open>
              <summary>Посмотреть итоговый запрос с текущими настройками</summary>
              <div className="top-gap">
                <p className="subtle">Метод: <b>{relayForm.method}</b> | URL: <b>{relayForm.url || '— не заполнен —'}</b></p>
                <strong>Headers:</strong>
                <pre>{JSON.stringify(relayHeadersPreview, null, 2)}</pre>
                <strong>Payload, который уйдёт:</strong>
                <pre>{JSON.stringify(relayTemplatePreview, null, 2)}</pre>
              </div>
            </details>

            <InlineError message={inlineErrors.relayForm} />
            <div className="actions-row">
              <AsyncButton
                type="submit"
                loading={actionLoading.relayForm}
                idleText={editingRelayId ? 'Сохранить изменения' : 'Сохранить ретранслятор'}
                loadingText="Сохранение…"
              />
              {editingRelayId ? <button type="button" onClick={cancelRelayEdit}>Отмена</button> : null}
            </div>
          </form>

          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Store</th><th>Название</th><th>URL</th><th>Метод</th><th>Ссылка на чек</th><th>Активен</th><th>Действия</th></tr></thead>
              <tbody>
                {relayTargets.map((target) => (
                  <tr key={target.id}>
                    <td>{target.id}</td><td>{target.store_id}</td><td>{target.name}</td><td>{target.url}</td><td>{target.method}</td><td>{target.include_receipt_url ? 'Да' : 'Нет'}</td><td>{target.is_active ? 'Да' : 'Нет'}</td>
                    <td><button onClick={() => startEditRelayTarget(target)}>Редактировать</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {activeTab === 'telegram' && (
        <section className="stack">
          <form className="form" onSubmit={saveTelegramChannel}>
            <h2>{editingTelegramId ? 'Редактировать Telegram бота' : 'Добавить Telegram бота'}</h2>
            <p className="subtle">Выберите события галочками: бот будет присылать только их. Любое событие можно включить/выключить позже.</p>
            <div className="grid cols-2">
              <select value={telegramForm.store_id} onChange={(e) => setTelegramForm({ ...telegramForm, store_id: e.target.value })} required>
                <option value="">Выбрать магазин</option>
                {stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
              </select>
              <input placeholder="Название" value={telegramForm.name} onChange={(e) => setTelegramForm({ ...telegramForm, name: e.target.value })} required />
              <input placeholder="Bot token" value={telegramForm.bot_token} onChange={(e) => setTelegramForm({ ...telegramForm, bot_token: e.target.value })} required />
              <input placeholder="chat_id" value={telegramForm.chat_id} onChange={(e) => setTelegramForm({ ...telegramForm, chat_id: e.target.value })} required />
              <label>
                topic_id (опционально)
                <input placeholder="Например 123" value={telegramForm.topic_id} onChange={(e) => setTelegramForm({ ...telegramForm, topic_id: e.target.value })} />
                <small>Используйте для форум-темы в группе (message_thread_id).</small>
              </label>
              <label className="inline">
                <input type="checkbox" checked={telegramForm.include_receipt_url} onChange={(e) => setTelegramForm({ ...telegramForm, include_receipt_url: e.target.checked })} />
                Добавлять ссылку на чек
              </label>
            </div>

            <div className="events-grid">
              {telegramEventOptions.map((eventOption) => (
                <label key={eventOption.key} className="event-option">
                  <input
                    type="checkbox"
                    checked={telegramForm.events_json.includes(eventOption.key)}
                    onChange={() => toggleTelegramEvent(eventOption.key)}
                  />
                  <div>
                    <strong>{eventOption.title}</strong>
                    <small>{eventOption.hint}</small>
                    <code>{eventOption.key}</code>
                  </div>
                </label>
              ))}
            </div>

            <InlineError message={inlineErrors.telegramForm} />
            <div className="actions-row">
              <AsyncButton
                type="submit"
                loading={actionLoading.telegramForm}
                idleText={editingTelegramId ? 'Сохранить изменения' : 'Сохранить бота'}
                loadingText="Сохранение…"
              />
              {editingTelegramId ? <button type="button" onClick={cancelTelegramEdit}>Отмена</button> : null}
            </div>
          </form>

          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Store</th><th>Название</th><th>chat_id</th><th>topic_id</th><th>События</th><th>Действия</th></tr></thead>
              <tbody>
                {telegramChannels.map((channel) => (
                  <tr key={channel.id}>
                    <td>{channel.id}</td>
                    <td>{channel.store_id}</td>
                    <td>{channel.name}</td>
                    <td>{channel.chat_id}</td>
                    <td>{channel.topic_id || '-'}</td>
                    <td>{Array.isArray(channel.events_json) ? channel.events_json.join(', ') : ''}</td>
                    <td>
                      <div className="actions-row">
                        <button onClick={() => startEditTelegram(channel)}>Редактировать</button>
                        <AsyncButton
                          onClick={() => sendTelegramTest(channel.id)}
                          loading={actionLoading[`telegramTest:${channel.id}`]}
                          idleText="Тест"
                          loadingText="Отправка…"
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {activeTab === 'events' && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Store</th><th>Тип</th><th>Payment</th><th>Status</th><th>Relay</th><th>Дата</th></tr></thead>
            <tbody>
              {events.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td><td>{item.store_id}</td><td>{item.event_type}</td><td>{item.payment_id}</td><td>{item.status}</td><td>{item.relay_status}</td><td>{item.received_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'queue' && (
        <section className="stack">
          <InlineError message={inlineErrors.queueAction} />
          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Store</th><th>Payment</th><th>Тип</th><th>Status</th><th>Попытки</th><th>Ошибка</th><th></th></tr></thead>
              <tbody>
                {queue.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td><td>{item.store_id}</td><td>{item.payment_id}</td><td>{item.task_type}</td><td>{item.status}</td><td>{item.attempts}/{item.max_attempts}</td><td>{item.error_message || '-'}</td>
                    <td>
                      <AsyncButton
                        onClick={() => retryTask(item.id)}
                        loading={actionLoading[`retryTask:${item.id}`]}
                        idleText="Retry"
                        loadingText="Повтор…"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {activeTab === 'receipts' && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Store</th><th>Payment</th><th>UUID</th><th>Сумма</th><th>Статус</th><th>URL</th></tr></thead>
            <tbody>
              {receipts.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td><td>{item.store_id}</td><td>{item.payment_id}</td><td>{item.receipt_uuid}</td><td>{item.amount}</td><td>{item.status}</td>
                  <td>{item.receipt_url ? <a href={item.receipt_url} target="_blank" rel="noreferrer">Открыть</a> : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'logs' && (
        <section className="stack">
          <div className="form">
            <h2>Фильтр логов</h2>
            <input placeholder="Поиск по сообщению" value={logsSearch} onChange={(e) => setLogsSearch(e.target.value)} />
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Store</th><th>Level</th><th>Event</th><th>Сообщение</th><th>Context</th><th>Дата</th></tr></thead>
              <tbody>
                {logs.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td><td>{item.store_id || '-'}</td><td>{item.level}</td><td>{item.event}</td><td>{item.message}</td><td>{item.context ? JSON.stringify(item.context) : '-'}</td><td>{item.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {activeTab === 'maintenance' && (
        <section className="stack">
          <form className="form" onSubmit={saveMaintenanceSettings}>
            <h2>Очистка БД: сроки и лимиты</h2>
            <p className="subtle">Можно одновременно использовать срок хранения (дни) и лимит последних записей.</p>
            <div className="grid cols-2">
              <label>Логи: хранить дней<input type="number" min="0" value={maintenanceSettings.log_retention_days} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, log_retention_days: e.target.value })} /></label>
              <label>Логи: оставить последних<input type="number" min="0" value={maintenanceSettings.keep_last_logs} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, keep_last_logs: e.target.value })} /></label>
              <label>События: хранить дней<input type="number" min="0" value={maintenanceSettings.event_retention_days} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, event_retention_days: e.target.value })} /></label>
              <label>События: оставить последних<input type="number" min="0" value={maintenanceSettings.keep_last_events} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, keep_last_events: e.target.value })} /></label>
              <label>Очередь: хранить дней<input type="number" min="0" value={maintenanceSettings.queue_retention_days} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, queue_retention_days: e.target.value })} /></label>
              <label>Очередь: оставить последних<input type="number" min="0" value={maintenanceSettings.keep_last_queue} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, keep_last_queue: e.target.value })} /></label>
              <label>Чеки: хранить дней<input type="number" min="0" value={maintenanceSettings.receipt_retention_days} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, receipt_retention_days: e.target.value })} /></label>
              <label>Чеки: оставить последних<input type="number" min="0" value={maintenanceSettings.keep_last_receipts} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, keep_last_receipts: e.target.value })} /></label>
              <label>Интервал автоочистки (мин)<input type="number" min="1" value={maintenanceSettings.cleanup_interval_minutes} onChange={(e) => setMaintenanceSettings({ ...maintenanceSettings, cleanup_interval_minutes: e.target.value })} /></label>
            </div>
            <InlineError message={inlineErrors.maintenanceSettings} />
            <div className="actions-row">
              <AsyncButton type="submit" loading={actionLoading.maintenanceSettings} idleText="Сохранить настройки" loadingText="Сохранение…" />
              <AsyncButton type="button" onClick={runCleanupNow} loading={actionLoading.maintenanceCleanup} idleText="Запустить очистку сейчас" loadingText="Очистка…" />
            </div>
          </form>

          {lastCleanupResult ? (
            <div className="card">
              <h3>Результат последней ручной очистки</h3>
              <p>Логи: {lastCleanupResult.deleted_logs}, События: {lastCleanupResult.deleted_events}, Очередь: {lastCleanupResult.deleted_queue}, Чеки: {lastCleanupResult.deleted_receipts}</p>
              <p>Время: {lastCleanupResult.ran_at}</p>
            </div>
          ) : null}
        </section>
      )}

      {toast.message ? <div className={`toast ${toast.type}`}>{toast.message}</div> : null}
    </div>
  )
}

export default App
