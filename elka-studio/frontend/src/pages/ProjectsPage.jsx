import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { GEMINI_API_KEY_STORAGE_KEY, getProjects } from '../services/api';
import NewProjectForm from '../components/NewProjectForm';
import './ProjectsPage.css';

const statusColors = {
  active: '#22c55e',
  paused: '#facc15',
  failed: '#ef4444',
};

const ProjectsPage = () => {
  const [projects, setProjects] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isApiKeyConfigured, setIsApiKeyConfigured] = useState(() => {
    if (typeof window === 'undefined') {
      return false;
    }

    return Boolean(window.localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY));
  });
  const navigate = useNavigate();

  const loadProjects = useCallback(async () => {
    if (!isApiKeyConfigured) {
      setProjects([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const response = await getProjects();
      setProjects(response.data || []);
    } catch (apiError) {
      const message = apiError.response?.data?.detail || 'Nepodařilo se načíst projekty.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [isApiKeyConfigured]);

  const refreshApiKeyState = useCallback(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const hasKey = Boolean(window.localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY));
    setIsApiKeyConfigured(hasKey);
  }, []);

  useEffect(() => {
    refreshApiKeyState();
  }, [refreshApiKeyState]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      refreshApiKeyState();
      void loadProjects();
    };

    window.addEventListener('focus', handleVisibilityChange);
    window.addEventListener('storage', handleVisibilityChange);

    return () => {
      window.removeEventListener('focus', handleVisibilityChange);
      window.removeEventListener('storage', handleVisibilityChange);
    };
  }, [loadProjects, refreshApiKeyState]);

  const handleProjectClick = (projectId) => {
    navigate(`/projects/${projectId}`);
  };

  return (
    <div className="projects-page">
      <header className="projects-page__header">
        <div>
          <h1>Projekty</h1>
          <p className="projects-page__subtitle">
            Spravujte generování lore a sledujte stav jednotlivých světů.
          </p>
        </div>
        <button
          type="button"
          className="projects-page__new-button"
          onClick={() => setIsModalOpen(true)}
          disabled={!isApiKeyConfigured}
        >
          + Add/Import Project
        </button>
      </header>

      {!isApiKeyConfigured ? (
        <div className="projects-page__welcome" role="status">
          <h2 className="projects-page__welcome-title">Welcome to eLKA Studio!</h2>
          <p className="projects-page__welcome-text">
            To get started, please configure your Gemini API Key in the Settings page. This unlocks the ability to
            browse and manage your lore universes.
          </p>
          <Link className="projects-page__welcome-action" to="/settings">
            Configure Gemini API Key
          </Link>
        </div>
      ) : (
        <>
          {isLoading && <div className="projects-page__placeholder">Načítám projekty…</div>}
          {error && <div className="projects-page__error">{error}</div>}

          {!isLoading && !error && (
            <section className="projects-page__grid" aria-live="polite">
              {projects.length === 0 ? (
                <div className="projects-page__placeholder projects-page__placeholder--empty">
                  Zatím žádné projekty. Založte první kliknutím na „Add/Import Project“.
                </div>
              ) : (
                projects.map((project) => (
                  <article
                    key={project.id}
                    className="projects-page__card"
                    role="button"
                    tabIndex={0}
                    onClick={() => handleProjectClick(project.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        handleProjectClick(project.id);
                      }
                    }}
                  >
                    <div className="projects-page__card-header">
                      <span className="projects-page__card-title">{project.name}</span>
                      <span
                        className="projects-page__status-dot"
                        style={{ backgroundColor: statusColors[project.status] || '#60a5fa' }}
                        aria-label={`Stav: ${project.status}`}
                      />
                    </div>
                    <p className="projects-page__card-meta">
                      {project.git_url || 'Bez repozitáře'}
                    </p>
                    <p className="projects-page__card-status">{project.status ?? 'neznámý stav'}</p>
                  </article>
                ))
              )}
            </section>
          )}
        </>
      )}

      {isModalOpen && (
        <NewProjectForm
          onClose={() => setIsModalOpen(false)}
          onCreated={() => {
            setIsModalOpen(false);
            void loadProjects();
          }}
        />
      )}
    </div>
  );
};

export default ProjectsPage;
