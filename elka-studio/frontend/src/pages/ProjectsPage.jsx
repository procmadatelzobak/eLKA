import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getProjects } from '../services/api';
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
  const navigate = useNavigate();

  const loadProjects = async () => {
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
  };

  useEffect(() => {
    loadProjects();
  }, []);

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
        <button type="button" className="projects-page__new-button" onClick={() => setIsModalOpen(true)}>
          + Nový projekt
        </button>
      </header>

      {isLoading && <div className="projects-page__placeholder">Načítám projekty…</div>}
      {error && <div className="projects-page__error">{error}</div>}

      {!isLoading && !error && (
        <section className="projects-page__grid" aria-live="polite">
          {projects.length === 0 ? (
            <div className="projects-page__placeholder projects-page__placeholder--empty">
              Zatím žádné projekty. Založte první kliknutím na „Nový projekt“.
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
                  {project.repository_url || 'Bez repozitáře'}
                </p>
                <p className="projects-page__card-status">{project.status ?? 'neznámý stav'}</p>
              </article>
            ))
          )}
        </section>
      )}

      {isModalOpen && (
        <NewProjectForm
          onClose={() => setIsModalOpen(false)}
          onCreated={() => {
            setIsModalOpen(false);
            loadProjects();
          }}
        />
      )}
    </div>
  );
};

export default ProjectsPage;
