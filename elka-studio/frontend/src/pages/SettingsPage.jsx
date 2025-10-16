import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GEMINI_API_KEY_STORAGE_KEY } from '../services/api';
import './SettingsPage.css';

const SettingsPage = () => {
  const navigate = useNavigate();
  const [apiKey, setApiKey] = useState('');
  const [status, setStatus] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const storedKey = window.localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY);
    if (storedKey) {
      setApiKey(storedKey);
    }
  }, []);

  const statusClassName = useMemo(() => {
    if (!status) {
      return '';
    }

    return `settings-page__status settings-page__status--${status.type}`;
  }, [status]);

  const handleSubmit = (event) => {
    event.preventDefault();
    setIsSaving(true);

    try {
      if (typeof window === 'undefined') {
        throw new Error('Nelze pracovat s úložištěm mimo prohlížeč.');
      }

      const trimmedKey = apiKey.trim();
      if (trimmedKey) {
        window.localStorage.setItem(GEMINI_API_KEY_STORAGE_KEY, trimmedKey);
        setStatus({ type: 'success', message: 'Gemini API Key byl uložen pro tento prohlížeč.' });
      } else {
        window.localStorage.removeItem(GEMINI_API_KEY_STORAGE_KEY);
        setStatus({ type: 'info', message: 'Gemini API Key byl odstraněn z tohoto prohlížeče.' });
      }
    } catch (error) {
      console.error('Failed to persist Gemini API Key', error);
      setStatus({ type: 'error', message: 'Nepodařilo se uložit nastavení. Zkuste to prosím znovu.' });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="settings-page">
      <header className="settings-page__header">
        <div>
          <h1>Nastavení</h1>
          <p className="settings-page__subtitle">
            Spravujte globální nastavení eLKA Studia. API klíče jsou ukládány pouze lokálně v tomto zařízení.
          </p>
        </div>
        <button type="button" className="settings-page__projects" onClick={() => navigate('/')}>↩ Zpět na projekty</button>
      </header>

      <section className="settings-page__card">
        <h2 className="settings-page__section-title">Gemini API Key</h2>
        <p className="settings-page__section-help">
          Tento klíč se používá k autorizaci všech požadavků na generativní AI. Ukládá se do localStorage a nikdy neopustí
          váš počítač.
        </p>

        <form className="settings-page__form" onSubmit={handleSubmit}>
          <label className="settings-page__field" htmlFor="geminiApiKey">
            <span>Gemini API Key</span>
            <input
              id="geminiApiKey"
              type="password"
              name="geminiApiKey"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="Skopírujte sem svůj tajný klíč"
            />
          </label>

          {status && (
            <div className={statusClassName} role="status" aria-live="polite">
              {status.message}
            </div>
          )}

          <footer className="settings-page__actions">
            <button type="submit" className="settings-page__primary" disabled={isSaving}>
              {isSaving ? 'Ukládám…' : 'Uložit klíč'}
            </button>
            <button type="button" className="settings-page__secondary" onClick={() => navigate('/')}>Zobrazit projekty</button>
          </footer>
        </form>
      </section>
    </div>
  );
};

export default SettingsPage;
