import { useEffect, useMemo, useState } from 'react'
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
  return response.json()
}

function formatErrorMessage(error) {
  if (!(error instanceof Error)) {
    return 'Неизвестная ошибка'
  }
  const raw = (error.message || '').trim()
  if (!raw) return 'Неизвестная ошибка'
  try {
    const parsed = JSON.parse(raw)
    if (parsed?.detail && typeof parsed.detail === 'string') {
      return parsed.detail
    }
    if (parsed?.message && typeof parsed.message === 'string') {
      return parsed.message
    }
    return JSON.stringify(parsed)
  } catch {
    return raw
  }
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
  const [error, setError] = useState('')
  const [editingProfileId, setEditingProfileId] = useState(null)
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
    is_active: true,
  })

  const [telegramForm, setTelegramForm] = useState({
    store_id: '',
    name: '',
    bot_token: '',
    chat_id: '',
    topic_id: '',
    events_json: 'payment_received,receipt_created,receipt_canceled,mytax_auth_required',
    include_receipt_url: true,
    is_active: true,
  })

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

  const loadAll = async () => {
    setLoading(true)
    setError('')
    try {
      const [
        storesRes,
        profilesRes,
        relayRes,
        telegramRes,
        eventsRes,
        queueRes,
        receiptsRes,
        logsRes,
        statsRes,
      ] = await Promise.all([
        api('/stores'),
        api('/profiles'),
        api(`/relay-targets${selectedStoreId ? `?store_id=${selectedStoreId}` : ''}`),
        api(`/telegram-channels${selectedStoreId ? `?store_id=${selectedStoreId}` : ''}`),
        api(`/events${querySuffix}`),
        api(`/queue${selectedStoreId ? `?store_id=${selectedStoreId}` : ''}`),
        api(`/receipts${querySuffix}`),
        api(`/logs${logsQuerySuffix}`),
        api(`/stats${querySuffix}`),
      ])
      setStores(storesRes)
      setProfiles(profilesRes)
      setRelayTargets(relayRes)
      setTelegramChannels(telegramRes)
      setEvents(eventsRes)
      setQueue(queueRes)
      setReceipts(receiptsRes)
      setLogs(logsRes)
      setStats(statsRes)
    } catch (err) {
      setError(formatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [querySuffix, selectedStoreId, logsQuerySuffix])

  const createStore = async (event) => {
    event.preventDefault()
    try {
      await api('/stores', {
        method: 'POST',
        body: JSON.stringify({
          ...storeForm,
          relay_retry_limit: Number(storeForm.relay_retry_limit),
          mytax_profile_id: storeForm.mytax_profile_id ? Number(storeForm.mytax_profile_id) : null,
        }),
      })
      setStoreForm({ ...storeForm, name: '', webhook_path: '' })
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  const createProfile = async (event) => {
    event.preventDefault()
    try {
      await api(editingProfileId ? `/profiles/${editingProfileId}` : '/profiles', {
        method: editingProfileId ? 'PUT' : 'POST',
        body: JSON.stringify(profileForm),
      })
      setProfileForm(emptyProfileForm)
      setEditingProfileId(null)
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  const loginProfile = async (profileId) => {
    try {
      await api(`/profiles/${profileId}/login`, {
        method: 'POST',
        body: JSON.stringify({ force: true }),
      })
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  const checkProfileAuth = async (profileId) => {
    try {
      const result = await api(`/profiles/${profileId}/auth/check`, {
        method: 'POST',
      })
      if (!result.is_authenticated) {
        setError(result.message || 'Проверка авторизации неуспешна')
      }
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  const startPhoneAuth = async (profile) => {
    try {
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
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  const verifyPhoneAuth = async (event) => {
    event.preventDefault()
    if (!phoneAuthForm.profile_id) return
    try {
      await api(`/profiles/${phoneAuthForm.profile_id}/auth/phone/verify`, {
        method: 'POST',
        body: JSON.stringify({
          phone: phoneAuthForm.phone,
          challenge_token: phoneAuthForm.challenge_token,
          code: phoneAuthForm.code,
        }),
      })
      setPhoneAuthForm({ profile_id: '', phone: '', challenge_token: '', code: '', expire_date: '' })
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
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
    try {
      await api(`/profiles/${profileId}`, { method: 'DELETE' })
      if (editingProfileId === profileId) {
        cancelProfileEdit()
      }
      if (String(phoneAuthForm.profile_id) === String(profileId)) {
        setPhoneAuthForm({ profile_id: '', phone: '', challenge_token: '', code: '', expire_date: '' })
      }
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  const loadProfileLogs = async (profileId) => {
    if (!profileId) {
      setSelectedProfileLogsId('')
      setProfileLogs([])
      return
    }
    try {
      setProfileLogsLoading(true)
      setSelectedProfileLogsId(String(profileId))
      const data = await api(`/profiles/${profileId}/logs?limit=150`)
      setProfileLogs(Array.isArray(data) ? data : [])
    } catch (err) {
      setError(formatErrorMessage(err))
    } finally {
      setProfileLogsLoading(false)
    }
  }

  const createRelayTarget = async (event) => {
    event.preventDefault()
    try {
      await api('/relay-targets', {
        method: 'POST',
        body: JSON.stringify({
          ...relayForm,
          store_id: Number(relayForm.store_id),
          headers_json: relayForm.headers_json ? JSON.parse(relayForm.headers_json) : {},
        }),
      })
      setRelayForm({ ...relayForm, name: '', url: '' })
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  const createTelegramChannel = async (event) => {
    event.preventDefault()
    try {
      await api('/telegram-channels', {
        method: 'POST',
        body: JSON.stringify({
          ...telegramForm,
          store_id: Number(telegramForm.store_id),
          topic_id: telegramForm.topic_id ? Number(telegramForm.topic_id) : null,
          events_json: telegramForm.events_json
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean),
        }),
      })
      setTelegramForm({ ...telegramForm, name: '', bot_token: '', chat_id: '', topic_id: '' })
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  const retryTask = async (taskId) => {
    try {
      await api('/queue/retry', {
        method: 'POST',
        body: JSON.stringify({ task_id: taskId }),
      })
      await loadAll()
    } catch (err) {
      setError(formatErrorMessage(err))
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <h1>YooKassa Auto MyTax Relay</h1>
          <p>Авто-чек в «Мой налог», очередь, ретрансляция вебхуков, Telegram-уведомления</p>
        </div>
        <button onClick={loadAll} disabled={loading}>{loading ? 'Обновление…' : 'Обновить'}</button>
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

      {error ? <div className="error">{error}</div> : null}

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
          <form className="form" onSubmit={createStore}>
            <h2>Добавить магазин</h2>
            <div className="grid cols-2">
              <input placeholder="Название" value={storeForm.name} onChange={(e) => setStoreForm({ ...storeForm, name: e.target.value })} required />
              <input placeholder="Webhook path (например shop-a)" value={storeForm.webhook_path} onChange={(e) => setStoreForm({ ...storeForm, webhook_path: e.target.value })} required />
              <select value={storeForm.relay_mode} onChange={(e) => setStoreForm({ ...storeForm, relay_mode: e.target.value })}>
                <option value="fire_and_forget">fire_and_forget</option>
                <option value="retry_until_200">retry_until_200</option>
              </select>
              <input type="number" min="1" value={storeForm.relay_retry_limit} onChange={(e) => setStoreForm({ ...storeForm, relay_retry_limit: e.target.value })} />
              <input placeholder="Шаблон описания" value={storeForm.description_template} onChange={(e) => setStoreForm({ ...storeForm, description_template: e.target.value })} />
              <select value={storeForm.mytax_profile_id ?? ''} onChange={(e) => setStoreForm({ ...storeForm, mytax_profile_id: e.target.value || null })}>
                <option value="">Без профиля</option>
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>{profile.name}</option>
                ))}
              </select>
            </div>
            <label className="inline"><input type="checkbox" checked={storeForm.include_receipt_url_in_relay} onChange={(e) => setStoreForm({ ...storeForm, include_receipt_url_in_relay: e.target.checked })} />Добавлять ссылку на чек в ретрансляцию</label>
            <label className="inline"><input type="checkbox" checked={storeForm.auto_cancel_on_refund} onChange={(e) => setStoreForm({ ...storeForm, auto_cancel_on_refund: e.target.checked })} />Авто-отмена чека при возврате</label>
            <button type="submit">Сохранить магазин</button>
          </form>

          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Название</th><th>Webhook</th><th>Профиль</th><th>Режим relay</th><th>Активен</th></tr></thead>
              <tbody>
                {stores.map((store) => (
                  <tr key={store.id}>
                    <td>{store.id}</td>
                    <td>{store.name}</td>
                    <td>/webhook/{store.webhook_path}</td>
                    <td>{store.mytax_profile_id || '-'}</td>
                    <td>{store.relay_mode}</td>
                    <td>{store.is_active ? 'Да' : 'Нет'}</td>
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
            <div className="actions-row">
              <button type="submit">{editingProfileId ? 'Сохранить изменения' : 'Сохранить профиль'}</button>
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
              <div className="actions-row">
                <button type="submit">Подтвердить код</button>
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
                        <button onClick={() => loginProfile(profile.id)}>Войти/переавторизовать</button>
                        <button onClick={() => checkProfileAuth(profile.id)}>Проверить сессию</button>
                        <button onClick={() => startPhoneAuth(profile)}>Запросить SMS</button>
                        <button onClick={() => startEditProfile(profile)}>Редактировать</button>
                        <button onClick={() => loadProfileLogs(profile.id)}>Auth-логи</button>
                        <button onClick={() => deleteProfile(profile.id)}>Удалить</button>
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
            <h2>Добавить ретранслятор</h2>
            <div className="grid cols-2">
              <select value={relayForm.store_id} onChange={(e) => setRelayForm({ ...relayForm, store_id: e.target.value })} required>
                <option value="">Выбрать магазин</option>
                {stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
              </select>
              <input placeholder="Название" value={relayForm.name} onChange={(e) => setRelayForm({ ...relayForm, name: e.target.value })} required />
              <input placeholder="URL" value={relayForm.url} onChange={(e) => setRelayForm({ ...relayForm, url: e.target.value })} required />
              <input placeholder="Метод" value={relayForm.method} onChange={(e) => setRelayForm({ ...relayForm, method: e.target.value })} />
              <input placeholder='Headers JSON, напр. {"Authorization":"Bearer ..."}' value={relayForm.headers_json} onChange={(e) => setRelayForm({ ...relayForm, headers_json: e.target.value })} />
              <input placeholder='Шаблон payload, напр. {"payment":"{{object.id}}"}' value={relayForm.payload_template} onChange={(e) => setRelayForm({ ...relayForm, payload_template: e.target.value })} />
            </div>
            <button type="submit">Сохранить ретранслятор</button>
          </form>

          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Store</th><th>Название</th><th>URL</th><th>Метод</th><th>Активен</th></tr></thead>
              <tbody>
                {relayTargets.map((target) => (
                  <tr key={target.id}>
                    <td>{target.id}</td><td>{target.store_id}</td><td>{target.name}</td><td>{target.url}</td><td>{target.method}</td><td>{target.is_active ? 'Да' : 'Нет'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {activeTab === 'telegram' && (
        <section className="stack">
          <form className="form" onSubmit={createTelegramChannel}>
            <h2>Добавить Telegram уведомления</h2>
            <div className="grid cols-2">
              <select value={telegramForm.store_id} onChange={(e) => setTelegramForm({ ...telegramForm, store_id: e.target.value })} required>
                <option value="">Выбрать магазин</option>
                {stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
              </select>
              <input placeholder="Название" value={telegramForm.name} onChange={(e) => setTelegramForm({ ...telegramForm, name: e.target.value })} required />
              <input placeholder="Bot token" value={telegramForm.bot_token} onChange={(e) => setTelegramForm({ ...telegramForm, bot_token: e.target.value })} required />
              <input placeholder="chat_id" value={telegramForm.chat_id} onChange={(e) => setTelegramForm({ ...telegramForm, chat_id: e.target.value })} required />
              <input placeholder="topic_id (опционально)" value={telegramForm.topic_id} onChange={(e) => setTelegramForm({ ...telegramForm, topic_id: e.target.value })} />
              <input placeholder="events через запятую" value={telegramForm.events_json} onChange={(e) => setTelegramForm({ ...telegramForm, events_json: e.target.value })} />
            </div>
            <label className="inline"><input type="checkbox" checked={telegramForm.include_receipt_url} onChange={(e) => setTelegramForm({ ...telegramForm, include_receipt_url: e.target.checked })} />Добавлять ссылку на чек</label>
            <button type="submit">Сохранить канал</button>
          </form>

          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Store</th><th>Название</th><th>chat_id</th><th>topic_id</th><th>События</th></tr></thead>
              <tbody>
                {telegramChannels.map((channel) => (
                  <tr key={channel.id}>
                    <td>{channel.id}</td>
                    <td>{channel.store_id}</td>
                    <td>{channel.name}</td>
                    <td>{channel.chat_id}</td>
                    <td>{channel.topic_id || '-'}</td>
                    <td>{channel.events_json.join(', ')}</td>
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
        <div className="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Store</th><th>Payment</th><th>Тип</th><th>Status</th><th>Попытки</th><th>Ошибка</th><th></th></tr></thead>
            <tbody>
              {queue.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td><td>{item.store_id}</td><td>{item.payment_id}</td><td>{item.task_type}</td><td>{item.status}</td><td>{item.attempts}/{item.max_attempts}</td><td>{item.error_message || '-'}</td>
                  <td><button onClick={() => retryTask(item.id)}>Retry</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
    </div>
  )
}

export default App
