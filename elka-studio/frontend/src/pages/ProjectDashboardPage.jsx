import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import TaskSocket from '../services/websocket';
import { createTask, pauseTask, resumeTask } from '../services/api';
import './ProjectDashboardPage.css';

const statusColors = {
  pending: '#facc15',
  running: '#3b82f6',
  completed: '#22c55e',
  failed: '#ef4444',
  paused: '#f97316',
};

const taskActionMessages = {
  pause: 'Úloha byla pozastavena.',
  resume: 'Úloha byla znovu spuštěna.',
};

const ProjectDashboardPage = () => {
  const { projectId } = useParams();
  const [tasks, setTasks] = useState([]);
  const [activeTab, setActiveTab] = useState('process_story');
  const [storyContent, setStoryContent] = useState('');
  const [seedValue, setSeedValue] = useState('');
  const [sagaTheme, setSagaTheme] = useState('');
  const [sagaChapters, setSagaChapters] = useState(3);
  const [formError, setFormError] = useState(null);
  const [formMessage, setFormMessage] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [taskActionError, setTaskActionError] = useState(null);
  const [taskActionMessage, setTaskActionMessage] = useState(null);
  const [expandedTasks, setExpandedTasks] = useState([]);
  const [pendingActions, setPendingActions] = useState({});
  const [modalContent, setModalContent] = useState(null);

  useEffect(() => {
    const socket = new TaskSocket();
    socket.connect(projectId, (updates) => {
      setTasks(Array.isArray(updates) ? updates : []);
    });

    return () => {
      socket.disconnect();
    };
  }, [projectId]);

  useEffect(() => {
    setFormError(null);
    setFormMessage(null);
  }, [activeTab]);

  useEffect(() => {
    if (!modalContent) {
      return undefined;
    }

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setModalContent(null);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [modalContent]);

  const sortedTasks = useMemo(() => {
    if (!Array.isArray(tasks)) {
      return [];
    }

    return [...tasks].sort((first, second) => {
      const firstDate = first?.created_at ? new Date(first.created_at).getTime() : 0;
      const secondDate = second?.created_at ? new Date(second.created_at).getTime() : 0;

      return secondDate - firstDate;
    });
  }, [tasks]);

  const isTaskExpanded = (taskId) => expandedTasks.includes(taskId);

  const toggleTaskExpansion = (taskId) => {
    setExpandedTasks((previous) =>
      previous.includes(taskId)
        ? previous.filter((currentId) => currentId !== taskId)
        : [...previous, taskId],
    );
  };

  const getProgressValue = (task) => {
    const raw = Number(task?.progress ?? 0);

    if (Number.isNaN(raw)) {
      return 0;
    }

    return Math.min(100, Math.max(0, raw));
  };

  const setPendingState = (taskId, action, value) => {
    const key = `${taskId}:${action}`;
    setPendingActions((previous) => {
      if (value) {
        return { ...previous, [key]: true };
      }

      const updated = { ...previous };
      delete updated[key];
      return updated;
    });
  };

  const isPendingAction = (taskId, action) => Boolean(pendingActions[`${taskId}:${action}`]);

  const handleTaskAction = async (taskId, action) => {
    setTaskActionError(null);
    setTaskActionMessage(null);
    setPendingState(taskId, action, true);

    try {
      if (action === 'pause') {
        await pauseTask(taskId);
      } else if (action === 'resume') {
        await resumeTask(taskId);
      }

      if (taskActionMessages[action]) {
        setTaskActionMessage(taskActionMessages[action]);
      }
    } catch (error) {
      const detail = error.response?.data?.detail || 'Nepodařilo se provést akci.';
      setTaskActionError(detail);
    } finally {
      setPendingState(taskId, action, false);
    }
  };

  const closeModal = () => setModalContent(null);

  const openStoryModal = (task) => {
    const story = task?.result?.story;
    if (!story) {
      return;
    }

    setModalContent({
      type: 'story',
      title: `Příběh úlohy #${task.id}`,
      data: {
        story,
        seed: task?.params?.seed ?? null,
      },
    });
  };

  const openFilesModal = (task) => {
    const files = task?.result?.files;
    if (!files || Object.keys(files).length === 0) {
      return;
    }

    setModalContent({
      type: 'files',
      title: `Soubory zpracování #${task.id}`,
      data: {
        files,
        metadata: task?.result?.metadata ?? null,
      },
    });
  };

  const handleSubmit = async (event, type) => {
    event.preventDefault();
    setFormError(null);
    setFormMessage(null);

    const payload = {
      project_id: projectId,
      type,
      params: {},
    };

    if (type === 'process_story') {
      if (!storyContent.trim()) {
        setFormError('Nejprve vložte text příběhu.');
        return;
      }
      const content = storyContent.trim();
      payload.params.story_content = content;
    }

    if (type === 'generate_story') {
      if (!seedValue.trim()) {
        setFormError('Zadejte seed pro generování.');
        return;
      }
      const seed = seedValue.trim();
      payload.seed = seed;
      payload.params.seed = seed;
    }

    if (type === 'generate_saga') {
      if (!sagaTheme.trim()) {
        setFormError('Zadejte téma ságy.');
        return;
      }

      const chapters = Number(sagaChapters);
      if (!Number.isFinite(chapters) || chapters <= 0) {
        setFormError('Počet kapitol musí být kladné číslo.');
        return;
      }

      const theme = sagaTheme.trim();
      payload.theme = theme;
      payload.chapters = chapters;
      payload.params.theme = theme;
      payload.params.chapters = chapters;
    }

    setIsSubmitting(true);

    try {
      await createTask(payload);
      setFormMessage('Úloha byla úspěšně odeslána agentovi eLKA.');

      if (type === 'process_story') {
        setStoryContent('');
      } else if (type === 'generate_story') {
        setSeedValue('');
      } else {
        setSagaTheme('');
        setSagaChapters(3);
      }
    } catch (error) {
      const detail = error.response?.data?.detail || 'Odeslání úlohy se nezdařilo.';
      setFormError(detail);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="project-dashboard">
      <header className="project-dashboard__header">
        <div>
          <h1>Projektový dashboard</h1>
          <p className="project-dashboard__subtitle">
            Spravujte úlohy projektu <strong>#{projectId}</strong>, odesílejte nové požadavky a sledujte jejich průběh.
          </p>
        </div>
      </header>

      <div className="project-dashboard__layout">
        <section className="project-dashboard__panel project-dashboard__panel--control" aria-label="Ovládací panel">
          <h2>Nová úloha</h2>
          <div className="task-forms">
            <div className="task-forms__tabs" role="tablist" aria-label="Typy úloh">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'process_story'}
                className={`task-forms__tab ${activeTab === 'process_story' ? 'task-forms__tab--active' : ''}`}
                onClick={() => setActiveTab('process_story')}
              >
                Zpracovat příběh
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'generate_story'}
                className={`task-forms__tab ${activeTab === 'generate_story' ? 'task-forms__tab--active' : ''}`}
                onClick={() => setActiveTab('generate_story')}
              >
                Vygenerovat z seed
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'generate_saga'}
                className={`task-forms__tab ${activeTab === 'generate_saga' ? 'task-forms__tab--active' : ''}`}
                onClick={() => setActiveTab('generate_saga')}
              >
                Vytvořit ságu
              </button>
            </div>

            <div className="task-forms__content">
              {formError && <div className="task-forms__alert task-forms__alert--error">{formError}</div>}
              {formMessage && <div className="task-forms__alert task-forms__alert--success">{formMessage}</div>}

              {activeTab === 'process_story' && (
                <form className="task-form" onSubmit={(event) => handleSubmit(event, 'process_story')}>
                  <label className="task-form__label" htmlFor="story-content">
                    Příběh ke zpracování
                  </label>
                  <textarea
                    id="story-content"
                    className="task-form__textarea"
                    value={storyContent}
                    onChange={(event) => setStoryContent(event.target.value)}
                    rows={10}
                    placeholder="Vložte text příběhu, který má eLKA analyzovat nebo rozšířit."
                  />
                  <button type="submit" className="task-form__submit" disabled={isSubmitting}>
                    {isSubmitting ? 'Odesílám…' : 'Odeslat'}
                  </button>
                </form>
              )}

              {activeTab === 'generate_story' && (
                <form className="task-form" onSubmit={(event) => handleSubmit(event, 'generate_story')}>
                  <label className="task-form__label" htmlFor="seed-value">
                    Seed
                  </label>
                  <input
                    id="seed-value"
                    type="text"
                    className="task-form__input"
                    value={seedValue}
                    onChange={(event) => setSeedValue(event.target.value)}
                    placeholder="Např. tajemná knihovna v horách"
                  />
                  <button type="submit" className="task-form__submit" disabled={isSubmitting}>
                    {isSubmitting ? 'Odesílám…' : 'Odeslat'}
                  </button>
                </form>
              )}

              {activeTab === 'generate_saga' && (
                <form className="task-form" onSubmit={(event) => handleSubmit(event, 'generate_saga')}>
                  <label className="task-form__label" htmlFor="saga-theme">
                    Téma ságy
                  </label>
                  <input
                    id="saga-theme"
                    type="text"
                    className="task-form__input"
                    value={sagaTheme}
                    onChange={(event) => setSagaTheme(event.target.value)}
                    placeholder="Např. Vzestup strojového impéria"
                  />
                  <label className="task-form__label" htmlFor="saga-chapters">
                    Počet kapitol
                  </label>
                  <input
                    id="saga-chapters"
                    type="number"
                    min="1"
                    className="task-form__input"
                    value={sagaChapters}
                    onChange={(event) => setSagaChapters(event.target.value)}
                  />
                  <button type="submit" className="task-form__submit" disabled={isSubmitting}>
                    {isSubmitting ? 'Odesílám…' : 'Odeslat'}
                  </button>
                </form>
              )}
            </div>
          </div>
        </section>

        <section className="project-dashboard__panel project-dashboard__panel--queue" aria-label="Fronta úloh">
          <div className="task-queue__header">
            <h2>Fronta úloh</h2>
            <p className="task-queue__subtitle">Aktualizuje se v reálném čase pomocí WebSocketu.</p>
          </div>

          {taskActionError && <div className="task-forms__alert task-forms__alert--error">{taskActionError}</div>}
          {taskActionMessage && <div className="task-forms__alert task-forms__alert--success">{taskActionMessage}</div>}

          {sortedTasks.length === 0 ? (
            <div className="task-queue__empty">
              Žádné úlohy zatím nejsou. Odeslané požadavky se zde objeví okamžitě.
            </div>
          ) : (
            <div className="task-queue__list">
              {sortedTasks.map((task) => {
                const progressValue = getProgressValue(task);
                const statusColor = statusColors[task.status] || '#94a3b8';
                const expanded = isTaskExpanded(task.id);
                const storyText = typeof task?.result?.story === 'string' ? task.result.story.trim() : '';
                const files = task?.result?.files;
                const hasStory = storyText.length > 0;
                const hasFiles = files && Object.keys(files).length > 0;

                return (
                  <article key={task.id} className="task-card">
                    <header className="task-card__header">
                      <div>
                        <h3 className="task-card__title">
                          {task.type || 'neznámý typ'} <span className="task-card__id">#{task.id}</span>
                        </h3>
                        <div className="task-card__status">
                          <span className="task-card__status-dot" style={{ backgroundColor: statusColor }} />
                          <span>{task.status || 'neznámý stav'}</span>
                        </div>
                      </div>
                      <div className="task-card__actions">
                        <button
                          type="button"
                          className="task-card__action"
                          onClick={() => handleTaskAction(task.id, 'pause')}
                          disabled={isPendingAction(task.id, 'pause')}
                        >
                          {isPendingAction(task.id, 'pause') ? 'Pozastavuji…' : 'Pozastavit'}
                        </button>
                        <button
                          type="button"
                          className="task-card__action"
                          onClick={() => handleTaskAction(task.id, 'resume')}
                          disabled={isPendingAction(task.id, 'resume')}
                        >
                          {isPendingAction(task.id, 'resume') ? 'Obnovuji…' : 'Obnovit'}
                        </button>
                        <button type="button" className="task-card__action task-card__action--ghost" disabled>
                          Zrušit
                        </button>
                      </div>
                    </header>

                    <div className="task-card__progress" role="progressbar" aria-valuenow={progressValue} aria-valuemin="0" aria-valuemax="100">
                      <div className="task-card__progress-bar" style={{ width: `${progressValue}%` }} />
                    </div>

                    <div className="task-card__footer">
                      <span className="task-card__progress-value">{progressValue}%</span>
                      <button
                        type="button"
                        className="task-card__toggle"
                        onClick={() => toggleTaskExpansion(task.id)}
                        aria-expanded={expanded}
                      >
                        {expanded ? 'Skrýt log' : 'Zobrazit log'}
                      </button>
                    </div>

                    {(hasStory || hasFiles) && (
                      <div className="task-card__details">
                        {hasStory && (
                          <button
                            type="button"
                            className="task-card__detail-action"
                            onClick={() => openStoryModal(task)}
                          >
                            Zobrazit příběh
                          </button>
                        )}
                        {hasFiles && (
                          <button
                            type="button"
                            className="task-card__detail-action"
                            onClick={() => openFilesModal(task)}
                          >
                            Zobrazit soubory
                          </button>
                        )}
                      </div>
                    )}

                    {expanded && (
                      <div className="task-card__log">
                        {task.log ? <pre>{task.log}</pre> : <p className="task-card__log-placeholder">Záznam zatím není k dispozici.</p>}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {modalContent && (
        <div className="task-modal">
          <div className="task-modal__backdrop" role="presentation" onClick={closeModal} />
          <div className="task-modal__dialog" role="dialog" aria-modal="true" aria-label={modalContent.title}>
            <header className="task-modal__header">
              <h3>{modalContent.title}</h3>
              <button type="button" className="task-modal__close" onClick={closeModal} aria-label="Zavřít detail úlohy">
                ×
              </button>
            </header>

            <div className="task-modal__body">
              {modalContent.type === 'story' && (
                <div className="task-modal__story">
                  {modalContent.data.seed && (
                    <p className="task-modal__meta">
                      <strong>Seed:</strong> {modalContent.data.seed}
                    </p>
                  )}
                  <pre className="task-modal__story-text">{modalContent.data.story}</pre>
                </div>
              )}

              {modalContent.type === 'files' && (
                <div className="task-modal__files">
                  {modalContent.data.metadata?.summary && (
                    <p className="task-modal__meta">
                      <strong>Souhrn:</strong> {modalContent.data.metadata.summary}
                    </p>
                  )}
                  {modalContent.data.metadata?.relative_path && (
                    <p className="task-modal__meta">
                      <strong>Cílový soubor:</strong> {modalContent.data.metadata.relative_path}
                    </p>
                  )}
                  {Object.entries(modalContent.data.files || {}).length === 0 ? (
                    <p className="task-modal__placeholder">Žádné soubory nebyly vygenerovány.</p>
                  ) : (
                    Object.entries(modalContent.data.files || {}).map(([path, content]) => (
                      <section key={path} className="task-modal__file">
                        <header className="task-modal__file-header">
                          <h4>{path}</h4>
                        </header>
                        <pre className="task-modal__file-content">{content}</pre>
                      </section>
                    ))
                  )}
                </div>
              )}
            </div>

            <footer className="task-modal__footer">
              <button type="button" className="task-modal__close-button" onClick={closeModal}>
                Zavřít
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectDashboardPage;
