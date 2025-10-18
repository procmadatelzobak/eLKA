import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import TaskSocket from '../services/websocket';
import { createTask, deleteTask, getProject, pauseTask, resumeTask } from '../services/api';
import './ProjectDashboardPage.css';

const statusColors = {
  pending: '#facc15',
  running: '#3b82f6',
  completed: '#22c55e',
  failed: '#ef4444',
  paused: '#f97316',
};

const taskActionMessages = {
  pause: 'Task paused successfully.',
  resume: 'Task resumed successfully.',
};

const ProjectDashboardPage = () => {
  const { projectId } = useParams();
  const [tasks, setTasks] = useState([]);
  const [projectDetails, setProjectDetails] = useState(null);
  const [activeTab, setActiveTab] = useState('generate_story');
  const [seedValue, setSeedValue] = useState('');
  const [storyTitle, setStoryTitle] = useState('');
  const [storyAuthor, setStoryAuthor] = useState('eLKA User');
  const [storyContent, setStoryContent] = useState('');
  const [sagaTheme, setSagaTheme] = useState('');
  const [sagaTitle, setSagaTitle] = useState('');
  const [sagaAuthor, setSagaAuthor] = useState('eLKA User');
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
    let isMounted = true;

    const fetchProjectDetails = async () => {
      try {
        const response = await getProject(projectId);
        if (isMounted) {
          setProjectDetails(response.data || null);
        }
      } catch (error) {
        if (isMounted) {
          setProjectDetails(null);
        }
      }
    };

    fetchProjectDetails();

    return () => {
      isMounted = false;
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

  const projectName = projectDetails?.name ? projectDetails.name : `Project #${projectId}`;
  const estimatedTokens =
    typeof projectDetails?.estimated_context_tokens === 'number'
      ? projectDetails.estimated_context_tokens.toLocaleString('en-US')
      : null;

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
      const detail = error.response?.data?.detail || 'Failed to perform the action.';
      setTaskActionError(detail);
    } finally {
      setPendingState(taskId, action, false);
    }
  };

  const handleDeleteTask = async (taskId) => {
    const confirmed = window.confirm('Are you sure you want to delete this task?');
    if (!confirmed) {
      return;
    }

    setTaskActionError(null);
    setTaskActionMessage(null);
    setPendingState(taskId, 'delete', true);

    try {
      await deleteTask(taskId);
      setTasks((previous) => previous.filter((task) => task.id !== taskId));
      setExpandedTasks((previous) => previous.filter((id) => id !== taskId));
      setTaskActionMessage('Task deleted successfully.');
    } catch (error) {
      const detail = error.response?.data?.detail || 'Failed to delete the task.';
      setTaskActionError(detail);
    } finally {
      setPendingState(taskId, 'delete', false);
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
      title: `Task #${task.id} story`,
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
      title: `Processing files for task #${task.id}`,
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

    if (type === 'generate_story') {
      if (!seedValue.trim()) {
        setFormError('Please provide a seed value.');
        return;
      }
      if (!storyTitle.trim()) {
        setFormError('Please provide a story or saga title.');
        return;
      }
      if (!storyAuthor.trim()) {
        setFormError('Please provide an author name.');
        return;
      }
      const seed = seedValue.trim();
      const title = storyTitle.trim();
      const author = storyAuthor.trim();
      payload.seed = seed;
      payload.params.seed = seed;
      payload.storyTitle = title;
      payload.storyAuthor = author;
      payload.params.storyTitle = title;
      payload.params.storyAuthor = author;
    }

    if (type === 'generate_saga') {
      if (!sagaTheme.trim()) {
        setFormError('Please provide a saga theme.');
        return;
      }
      if (!sagaTitle.trim()) {
        setFormError('Please provide a story or saga title.');
        return;
      }
      if (!sagaAuthor.trim()) {
        setFormError('Please provide an author name.');
        return;
      }

      const chapters = Number(sagaChapters);
      if (!Number.isFinite(chapters) || chapters <= 0) {
        setFormError('Chapter count must be a positive number.');
        return;
      }

      const theme = sagaTheme.trim();
      const title = sagaTitle.trim();
      const author = sagaAuthor.trim();
      payload.theme = theme;
      payload.chapters = chapters;
      payload.params.theme = theme;
      payload.params.chapters = chapters;
      payload.storyTitle = title;
      payload.storyAuthor = author;
      payload.params.storyTitle = title;
      payload.params.storyAuthor = author;
    }

    setIsSubmitting(true);

    try {
      await createTask(payload);
      setFormMessage('Task successfully submitted to eLKA.');

      if (type === 'generate_story') {
        setSeedValue('');
        setStoryTitle('');
        setStoryAuthor('eLKA User');
      } else if (type === 'generate_saga') {
        setSagaTheme('');
        setSagaTitle('');
        setSagaAuthor('eLKA User');
        setSagaChapters(3);
      }
    } catch (error) {
      const detail = error.response?.data?.detail || 'Submitting the task failed.';
      setFormError(detail);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleProcessStorySubmit = async (event) => {
    event.preventDefault();
    setFormError(null);
    setFormMessage(null);

    if (!storyContent.trim()) {
      setFormError('Please paste the story text you want to analyse.');
      return;
    }

    const payload = {
      project_id: projectId,
      type: 'process_story',
      params: {
        story_content: storyContent.trim(),
      },
    };

    setIsSubmitting(true);

    try {
      await createTask(payload);
      setFormMessage('Existing story submitted for processing.');
      setStoryContent('');
    } catch (error) {
      const detail = error.response?.data?.detail || 'Submitting the task failed.';
      setFormError(detail);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="project-dashboard">
      <header className="project-dashboard__header">
        <div>
          <h1>Project Dashboard</h1>
          <p className="project-dashboard__subtitle">
            Manage tasks for <strong>{projectName}</strong>, submit new requests, and monitor their progress in real time.
          </p>
          {estimatedTokens && (
            <p className="project-dashboard__meta">
              <strong>Estimated universe tokens:</strong> {estimatedTokens}
            </p>
          )}
        </div>
      </header>

      <div className="project-dashboard__layout">
        <section className="project-dashboard__panel project-dashboard__panel--control" aria-label="Control panel">
          <h2>New Task</h2>
          <div className="task-forms">
          <div className="task-forms__tabs" role="tablist" aria-label="Task types">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'generate_story'}
              className={`task-forms__tab ${
                  activeTab === 'generate_story'
                    ? 'task-forms__tab--active'
                    : ''
                }`}
              onClick={() => setActiveTab('generate_story')}
            >
              Generate Story
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'process_story'}
              className={`task-forms__tab ${activeTab === 'process_story' ? 'task-forms__tab--active' : ''}`}
              onClick={() => setActiveTab('process_story')}
            >
              Process Existing Story
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'generate_saga'}
              className={`task-forms__tab ${activeTab === 'generate_saga' ? 'task-forms__tab--active' : ''}`}
                onClick={() => setActiveTab('generate_saga')}
              >
                Create Saga
              </button>
            </div>

            <div className="task-forms__content">
              {formError && <div className="task-forms__alert task-forms__alert--error">{formError}</div>}
              {formMessage && <div className="task-forms__alert task-forms__alert--success">{formMessage}</div>}

              {activeTab === 'generate_story' && (
                <form
                  className="task-form"
                  onSubmit={(event) =>
                    handleSubmit(event, 'generate_story')
                  }
                >
                  <label className="task-form__label" htmlFor="story-title">
                    Story/Saga Title
                  </label>
                  <input
                    id="story-title"
                    type="text"
                    className="task-form__input"
                    value={storyTitle}
                    onChange={(event) => setStoryTitle(event.target.value)}
                    placeholder="e.g. Chronicles of Avalon"
                  />
                  <label className="task-form__label" htmlFor="story-author">
                    Author
                  </label>
                  <input
                    id="story-author"
                    type="text"
                    className="task-form__input"
                    value={storyAuthor}
                    onChange={(event) => setStoryAuthor(event.target.value)}
                    placeholder="e.g. eLKA User"
                  />
                  <label className="task-form__label" htmlFor="seed-value">
                    Seed
                  </label>
                  <input
                    id="seed-value"
                    type="text"
                    className="task-form__input"
                    value={seedValue}
                    onChange={(event) => setSeedValue(event.target.value)}
                    placeholder="e.g. a hidden library in the mountains"
                  />
                  <button type="submit" className="task-form__submit" disabled={isSubmitting}>
                    {isSubmitting ? 'Submitting…' : 'Submit'}
                  </button>
                </form>
              )}

              {activeTab === 'process_story' && (
                <form className="task-form" onSubmit={handleProcessStorySubmit}>
                  <label className="task-form__label" htmlFor="story-content">
                    Story text
                  </label>
                  <textarea
                    id="story-content"
                    className="task-form__textarea"
                    rows={8}
                    value={storyContent}
                    onChange={(event) => setStoryContent(event.target.value)}
                    placeholder="Paste the story you want to validate and archive"
                  />
                  <button type="submit" className="task-form__submit" disabled={isSubmitting}>
                    {isSubmitting ? 'Submitting…' : 'Submit'}
                  </button>
                </form>
              )}

              {activeTab === 'generate_saga' && (
                <form className="task-form" onSubmit={(event) => handleSubmit(event, 'generate_saga')}>
                  <label className="task-form__label" htmlFor="saga-title">
                    Story/Saga Title
                  </label>
                  <input
                    id="saga-title"
                    type="text"
                    className="task-form__input"
                    value={sagaTitle}
                    onChange={(event) => setSagaTitle(event.target.value)}
                    placeholder="e.g. Rise of the Machine Empire"
                  />
                  <label className="task-form__label" htmlFor="saga-author">
                    Author
                  </label>
                  <input
                    id="saga-author"
                    type="text"
                    className="task-form__input"
                    value={sagaAuthor}
                    onChange={(event) => setSagaAuthor(event.target.value)}
                    placeholder="e.g. eLKA User"
                  />
                  <label className="task-form__label" htmlFor="saga-theme">
                    Saga theme
                  </label>
                  <input
                    id="saga-theme"
                    type="text"
                    className="task-form__input"
                    value={sagaTheme}
                    onChange={(event) => setSagaTheme(event.target.value)}
                    placeholder="e.g. Rise of the Machine Empire"
                  />
                  <label className="task-form__label" htmlFor="saga-chapters">
                    Number of chapters
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
                    {isSubmitting ? 'Submitting…' : 'Submit'}
                  </button>
                </form>
              )}
            </div>
          </div>
        </section>

        <section className="project-dashboard__panel project-dashboard__panel--queue" aria-label="Task queue">
          <div className="task-queue__header">
            <h2>Task Queue</h2>
            <p className="task-queue__subtitle">Updates in real time via WebSocket.</p>
          </div>

          {taskActionError && <div className="task-forms__alert task-forms__alert--error">{taskActionError}</div>}
          {taskActionMessage && <div className="task-forms__alert task-forms__alert--success">{taskActionMessage}</div>}

          {sortedTasks.length === 0 ? (
            <div className="task-queue__empty">
              No tasks yet. Newly submitted requests will appear here immediately.
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
                const formatTokens = (value) =>
                  typeof value === 'number' && Number.isFinite(value)
                    ? value.toLocaleString('en-US')
                    : 'N/A';
                const inputTokensDisplay = formatTokens(task?.total_input_tokens);
                const outputTokensDisplay = formatTokens(task?.total_output_tokens);

                return (
                  <article key={task.id} className="task-card">
                    <header className="task-card__header">
                      <div>
                        <h3 className="task-card__title">
                          {task.type || 'Unknown type'} <span className="task-card__id">#{task.id}</span>
                        </h3>
                        <div className="task-card__status">
                          <span className="task-card__status-dot" style={{ backgroundColor: statusColor }} />
                          <span>{task.status || 'Unknown status'}</span>
                        </div>
                        <div className="task-card__tokens">
                          <span>Input: {inputTokensDisplay}</span>
                          <span>Output: {outputTokensDisplay}</span>
                        </div>
                      </div>
                      <div className="task-card__actions">
                        <button
                          type="button"
                          className="task-card__action"
                          onClick={() => handleTaskAction(task.id, 'pause')}
                          disabled={isPendingAction(task.id, 'pause')}
                        >
                          {isPendingAction(task.id, 'pause') ? 'Pausing…' : 'Pause'}
                        </button>
                        <button
                          type="button"
                          className="task-card__action"
                          onClick={() => handleTaskAction(task.id, 'resume')}
                          disabled={isPendingAction(task.id, 'resume')}
                        >
                          {isPendingAction(task.id, 'resume') ? 'Resuming…' : 'Resume'}
                        </button>
                        <button
                          type="button"
                          className="task-card__action task-card__action--ghost"
                          onClick={() => handleDeleteTask(task.id)}
                          disabled={isPendingAction(task.id, 'delete')}
                        >
                          {isPendingAction(task.id, 'delete') ? 'Deleting…' : 'Delete'}
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
                        {expanded ? 'Hide log' : 'Show log'}
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
                            Show story
                          </button>
                        )}
                        {hasFiles && (
                          <button
                            type="button"
                            className="task-card__detail-action"
                            onClick={() => openFilesModal(task)}
                          >
                            Show files
                          </button>
                        )}
                      </div>
                    )}

                    {expanded && (
                      <div className="task-card__log">
                        {task.log ? <pre>{task.log}</pre> : <p className="task-card__log-placeholder">Log is not available yet.</p>}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
          <p className="task-queue__note">
            <small>
              Note: Google AI Free Tier limits (for example, 125,000 input tokens per minute) apply to every task. Review the
              summary above each entry for the latest usage details.
            </small>
          </p>
        </section>
      </div>

      {modalContent && (
        <div className="task-modal">
          <div className="task-modal__backdrop" role="presentation" onClick={closeModal} />
          <div className="task-modal__dialog" role="dialog" aria-modal="true" aria-label={modalContent.title}>
            <header className="task-modal__header">
              <h3>{modalContent.title}</h3>
              <button type="button" className="task-modal__close" onClick={closeModal} aria-label="Close task detail">
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
                      <strong>Summary:</strong> {modalContent.data.metadata.summary}
                    </p>
                  )}
                  {modalContent.data.metadata?.relative_path && (
                    <p className="task-modal__meta">
                      <strong>Target file:</strong> {modalContent.data.metadata.relative_path}
                    </p>
                  )}
                  {Object.entries(modalContent.data.files || {}).length === 0 ? (
                    <p className="task-modal__placeholder">No files were generated.</p>
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
                Close
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectDashboardPage;
