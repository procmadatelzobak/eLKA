import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GEMINI_API_KEY_STORAGE_KEY, fetchAiSettings, updateAiSettings } from '../services/api';
import './SettingsPage.css';

const SettingsPage = () => {
  const navigate = useNavigate();
  const [apiKey, setApiKey] = useState('');
  const [status, setStatus] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [defaultAdapter, setDefaultAdapter] = useState('heuristic');
  const [isLoadingAdapter, setIsLoadingAdapter] = useState(true);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const storedKey = window.localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY);
    if (storedKey) {
      setApiKey(storedKey);
    }
  }, []);

  useEffect(() => {
    let active = true;
    fetchAiSettings()
      .then((settings) => {
        if (!active || !settings) {
          return;
        }
        if (settings.default_adapter) {
          setDefaultAdapter(settings.default_adapter);
        }
      })
      .catch((error) => {
        console.error('Failed to load AI settings', error);
        setStatus({
          type: 'error',
          message: 'Failed to load AI settings. Ensure config.yml exists on the server.',
        });
      })
      .finally(() => {
        if (active) {
          setIsLoadingAdapter(false);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  const statusClassName = useMemo(() => {
    if (!status) {
      return '';
    }

    return `settings-page__status settings-page__status--${status.type}`;
  }, [status]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsSaving(true);

    try {
      if (typeof window === 'undefined') {
        throw new Error('Local storage is only available in the browser.');
      }

      const trimmedKey = apiKey.trim();
      if (trimmedKey) {
        window.localStorage.setItem(GEMINI_API_KEY_STORAGE_KEY, trimmedKey);
      } else {
        window.localStorage.removeItem(GEMINI_API_KEY_STORAGE_KEY);
      }

      await updateAiSettings({ default_adapter: defaultAdapter });
      setStatus({
        type: 'success',
        message: 'Settings saved. Restart the backend to apply the new adapter.',
      });
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

          <label className="settings-page__field" htmlFor="defaultAdapter">
            <span>Default AI Adapter</span>
            <select
              id="defaultAdapter"
              name="defaultAdapter"
              value={defaultAdapter}
              onChange={(event) => setDefaultAdapter(event.target.value)}
              disabled={isLoadingAdapter || isSaving}
            >
              <option value="gemini">Gemini (cloud)</option>
              <option value="heuristic">Heuristic (offline fallback)</option>
            </select>
            <p className="settings-page__helper">
              Changes require a backend restart. Gemini mode also needs a valid API key.
            </p>
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
