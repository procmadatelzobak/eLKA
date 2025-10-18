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
        throw new Error('Local storage is only available in the browser.');
      }

      const trimmedKey = apiKey.trim();
      if (trimmedKey) {
        window.localStorage.setItem(GEMINI_API_KEY_STORAGE_KEY, trimmedKey);
        setStatus({ type: 'success', message: 'Gemini API Key saved for this browser.' });
      } else {
        window.localStorage.removeItem(GEMINI_API_KEY_STORAGE_KEY);
        setStatus({ type: 'info', message: 'Gemini API Key removed from this browser.' });
      }
    } catch (error) {
      console.error('Failed to persist Gemini API Key', error);
      setStatus({ type: 'error', message: 'Failed to save settings. Please try again.' });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="settings-page">
      <header className="settings-page__header">
        <div>
          <h1>Settings</h1>
          <p className="settings-page__subtitle">
            Manage global preferences for eLKA Studio. API keys are stored locally on this device only.
          </p>
        </div>
        <button type="button" className="settings-page__projects" onClick={() => navigate('/')}>↩ Back to projects</button>
      </header>

      <section className="settings-page__card">
        <h2 className="settings-page__section-title">Gemini API Key</h2>
        <p className="settings-page__section-help">
          This key authorises all generative AI requests. It is stored in localStorage and never leaves your computer.
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
              placeholder="Paste your secret key here"
            />
          </label>

          {status && (
            <div className={statusClassName} role="status" aria-live="polite">
              {status.message}
            </div>
          )}

          <footer className="settings-page__actions">
            <button type="submit" className="settings-page__primary" disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save key'}
            </button>
            <button type="button" className="settings-page__secondary" onClick={() => navigate('/')}>View projects</button>
          </footer>
        </form>
      </section>
    </div>
  );
};

export default SettingsPage;
