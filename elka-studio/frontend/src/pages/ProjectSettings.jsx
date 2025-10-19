import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import {
  fetchProjectAiModels,
  updateProjectAiModels,
} from '../services/api';
import './ProjectSettings.css';

const MODEL_OPTIONS = [
  { value: '', label: 'Use global default' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
];

const ProjectSettings = ({ projectId, onClose }) => {
  const [models, setModels] = useState({
    extraction: '',
    validation: '',
    generation: '',
    planning: '',
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    if (!projectId) {
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    fetchProjectAiModels(projectId)
      .then((data) => {
        if (!isMounted) {
          return;
        }
        setModels({
          extraction: data?.extraction ?? '',
          validation: data?.validation ?? '',
          generation: data?.generation ?? '',
          planning: data?.planning ?? '',
        });
      })
      .catch((fetchError) => {
        if (!isMounted) {
          return;
        }
        const detail = fetchError.response?.data?.detail;
        setError(detail || 'Unable to load AI settings for this project.');
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [projectId]);

  const handleChange = (key) => (event) => {
    setModels((previous) => ({ ...previous, [key]: event.target.value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!projectId) {
      return;
    }

    setIsSaving(true);
    setError(null);
    setMessage(null);

    try {
      const response = await updateProjectAiModels(projectId, models);
      setModels({
        extraction: response?.extraction ?? '',
        validation: response?.validation ?? '',
        generation: response?.generation ?? '',
        planning: response?.planning ?? '',
      });
      setMessage('AI settings saved successfully.');
    } catch (saveError) {
      const detail = saveError.response?.data?.detail;
      setError(detail || 'Saving AI settings failed.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="project-settings">
      <header className="project-settings__header">
        <div>
          <h3>Project AI Models</h3>
          <p>Override the AI models used for this project. Leave a field on "Use global default" to inherit the workspace configuration.</p>
        </div>
        {onClose && (
          <button type="button" className="project-settings__close" onClick={onClose}>
            Close
          </button>
        )}
      </header>

      {isLoading ? (
        <p className="project-settings__status">Loading current settings…</p>
      ) : (
        <form className="project-settings__form" onSubmit={handleSubmit}>
          {error && <div className="project-settings__alert project-settings__alert--error">{error}</div>}
          {message && <div className="project-settings__alert project-settings__alert--success">{message}</div>}

          <label className="project-settings__label" htmlFor="project-settings-extraction">
            Extraction model
          </label>
          <select
            id="project-settings-extraction"
            className="project-settings__select"
            value={models.extraction}
            onChange={handleChange('extraction')}
          >
            {MODEL_OPTIONS.map((option) => (
              <option key={option.value || 'default-extraction'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="project-settings__label" htmlFor="project-settings-validation">
            Validation model
          </label>
          <select
            id="project-settings-validation"
            className="project-settings__select"
            value={models.validation}
            onChange={handleChange('validation')}
          >
            {MODEL_OPTIONS.map((option) => (
              <option key={option.value || 'default-validation'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="project-settings__label" htmlFor="project-settings-generation">
            Generation model
          </label>
          <select
            id="project-settings-generation"
            className="project-settings__select"
            value={models.generation}
            onChange={handleChange('generation')}
          >
            {MODEL_OPTIONS.map((option) => (
              <option key={option.value || 'default-generation'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="project-settings__label" htmlFor="project-settings-planning">
            Planning model
          </label>
          <select
            id="project-settings-planning"
            className="project-settings__select"
            value={models.planning}
            onChange={handleChange('planning')}
          >
            {MODEL_OPTIONS.map((option) => (
              <option key={option.value || 'default-planning'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <footer className="project-settings__footer">
            <button type="submit" className="project-settings__submit" disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save AI settings'}
            </button>
          </footer>
        </form>
      )}
    </div>
  );
};

ProjectSettings.propTypes = {
  projectId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  onClose: PropTypes.func,
};

ProjectSettings.defaultProps = {
  onClose: undefined,
};

export default ProjectSettings;
