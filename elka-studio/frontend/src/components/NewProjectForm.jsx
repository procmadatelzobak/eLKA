import { useState } from 'react';
import PropTypes from 'prop-types';
import { createProject } from '../services/api';
import './NewProjectForm.css';

const initialFormState = {
  name: '',
  repository_url: '',
  access_token: '',
};

const NewProjectForm = ({ onClose, onCreated }) => {
  const [formData, setFormData] = useState(initialFormState);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      await createProject({
        name: formData.name.trim(),
        git_url: formData.repository_url.trim(),
        git_token: formData.access_token,
      });

      setSuccess('Projekt byl úspěšně vytvořen.');
      setFormData(initialFormState);
      if (onCreated) {
        onCreated();
      }
    } catch (apiError) {
      const { detail } = apiError.response?.data ?? {};
      let message = 'Vytvoření projektu selhalo.';

      if (Array.isArray(detail)) {
        message = detail
          .map((item) => {
            if (!item) return null;
            if (typeof item === 'string') return item;
            if (item.msg) {
              const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : item.loc;
              return field ? `${field}: ${item.msg}` : item.msg;
            }
            return JSON.stringify(item);
          })
          .filter(Boolean)
          .join(' ');
      } else if (detail) {
        message = detail;
      }

      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal">
      <div className="modal__backdrop" role="presentation" onClick={onClose} />
      <div className="modal__content" role="dialog" aria-modal="true">
        <header className="modal__header">
          <h2>Nový projekt</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Zavřít">
            ×
          </button>
        </header>
        <form className="modal__form" onSubmit={handleSubmit}>
          <p className="modal__description">
            If the repository is empty, eLKA will initialize it with a default universe structure. If the
            repository already contains a lore universe, eLKA will simply connect to it.
          </p>
          <label className="modal__field">
            <span>Název projektu</span>
            <input
              type="text"
              name="name"
              value={formData.name}
              onChange={handleChange}
              placeholder="Např. Kroniky Avalonu"
              required
              autoFocus
            />
          </label>

          <label className="modal__field">
            <span>Git repozitář</span>
            <input
              type="text"
              name="repository_url"
              value={formData.repository_url}
              onChange={handleChange}
              placeholder="uzivatel/projekt nebo https://example.com/repo.git"
              required
            />
          </label>

          <label className="modal__field">
            <span>Přístupový token</span>
            <input
              type="password"
              name="access_token"
              value={formData.access_token}
              onChange={handleChange}
              placeholder="***"
            />
          </label>

          {error && <div className="modal__alert modal__alert--error">{error}</div>}
          {success && <div className="modal__alert modal__alert--success">{success}</div>}

          <footer className="modal__footer">
            <button type="button" className="modal__secondary" onClick={onClose}>
              Zavřít
            </button>
            <button type="submit" className="modal__primary" disabled={isSubmitting}>
              {isSubmitting ? 'Vytvářím…' : 'Vytvořit projekt'}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
};

NewProjectForm.propTypes = {
  onClose: PropTypes.func.isRequired,
  onCreated: PropTypes.func,
};

NewProjectForm.defaultProps = {
  onCreated: null,
};

export default NewProjectForm;
