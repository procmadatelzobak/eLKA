import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import TaskSocket from '../services/websocket';
import TaskItem from '../components/TaskItem';
import {
  createTask,
  deleteTask,
  fetchProject,
  approveTask,
  importStories,
  pauseTask,
  resetProject,
  resumeTask,
  syncProject,
} from '../services/api';
import ProjectSettings from './ProjectSettings';
import './ProjectDashboardPage.css';

const taskActionMessages = {
  pause: 'Task paused successfully.',
  resume: 'Task resumed successfully.',
  approve: 'Task approved successfully.',
};

const ProjectDashboardPage = () => {
  const { projectId } = useParams();
  const [tasks, setTasks] = useState([]);
  const [projectDetails, setProjectDetails] = useState(null);
  const [projectName, setProjectName] = useState('');
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
  const [isResetting, setIsResetting] = useState(false);
  const [resetMessage, setResetMessage] = useState(null);
  const [resetError, setResetError] = useState(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState(null);
  const [syncError, setSyncError] = useState(null);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [importError, setImportError] = useState(null);
  const [importMessage, setImportMessage] = useState(null);
  const [isImporting, setIsImporting] = useState(false);
  const fileInputRef = useRef(null);

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
        const data = await fetchProject(projectId);
        if (isMounted) {
          setProjectDetails(data || null);
          setProjectName(typeof data?.name === 'string' ? data.name : '');
        }
      } catch (error) {
        if (isMounted) {
          console.warn('Failed to fetch project details.', error);
          setProjectDetails(null);
          setProjectName('');
        }
      }
    };

    fetchProjectDetails();

    return () => {
      isMounted = false;
    };
  }, [projectId]);

  useEffect(() => {
    setResetMessage(null);
    setResetError(null);
    setSyncMessage(null);
    setSyncError(null);
    setIsSyncing(false);
    setImportError(null);
    setImportMessage(null);
    setSelectedFiles([]);
    setIsImporting(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, [projectId]);

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

  const topLevelTasks = useMemo(
    () => sortedTasks.filter((task) => !task.parent_task_id),
    [sortedTasks],
  );

  const headingProjectName = projectName || projectDetails?.name || 'Loading…';
  const resolvedProjectName = projectName || projectDetails?.name || `Project #${projectId}`;
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

  const handleApproveTask = async (taskId) => {
    setTaskActionError(null);
    setTaskActionMessage(null);
    setPendingState(taskId, 'approve', true);

    try {
      const approvedTask = await approveTask(taskId);
      if (approvedTask && typeof approvedTask === 'object') {
        setTasks((previous) =>
          Array.isArray(previous)
            ? previous.map((task) => (task.id === taskId ? { ...task, ...approvedTask } : task))
            : previous,
        );
      }

      if (taskActionMessages.approve) {
        setTaskActionMessage(taskActionMessages.approve);
      }
    } catch (error) {
      const detail = error.response?.data?.detail || 'Failed to approve the task.';
      setTaskActionError(detail);
    } finally {
      setPendingState(taskId, 'approve', false);
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
      const wasDeleted = await deleteTask(taskId);
      if (wasDeleted) {
        setTasks((previous) => previous.filter((task) => task.id !== taskId));
        setExpandedTasks((previous) => previous.filter((id) => id !== taskId));
        setTaskActionMessage(`Task ${taskId} deleted successfully.`);
      } else {
        setTaskActionError('Failed to delete the task.');
      }
    } catch (error) {
      const detail = error.response?.data?.detail || 'Failed to delete the task.';
      setTaskActionError(detail);
    } finally {
      setPendingState(taskId, 'delete', false);
    }
  };

  const handleResetUniverse = async () => {
    const confirmed = window.confirm(
      'Resetting the universe removes Stories, Legends, Objects, and timeline files before restoring the default scaffold. Continue?'
    );

    if (!confirmed) {
      return;
    }

    setIsResetting(true);
    setResetError(null);
    setResetMessage(null);

    try {
      await resetProject(projectId);
      setResetMessage('Universe reset successfully. Fresh scaffold committed.');
    } catch (error) {
      const detail = error.response?.data?.detail || 'Failed to reset the universe.';
      setResetError(detail);
    } finally {
      setIsResetting(false);
    }
  };

  const handleSynchroniseRepository = async () => {
    setSyncError(null);
    setSyncMessage(null);
    setIsSyncing(true);

    try {
      const response = await syncProject(projectId);
      const detail = response?.data?.detail || 'Repository synchronised with the remote server.';
      setSyncMessage(detail);

      try {
        const data = await fetchProject(projectId);
        setProjectDetails(data || null);
        setProjectName(typeof data?.name === 'string' ? data.name : '');
      } catch (refreshError) {
        console.warn('Failed to refresh project details after synchronisation.', refreshError);
      }
    } catch (error) {
      const detail = error.response?.data?.detail || 'Failed to synchronise with the server.';
      setSyncError(detail);
    } finally {
      setIsSyncing(false);
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

  const openProjectSettings = () => {
    setModalContent({
      type: 'project-settings',
      title: 'Project AI Settings',
      data: { projectId },
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

    const form = event.currentTarget;
    const formData = new FormData(form);
    const rawTitle = formData.get('storyTitle');
    const rawAuthor = formData.get('storyAuthor');
    const storyTitleValue = typeof rawTitle === 'string' ? rawTitle.trim() : '';
    const storyAuthorValue = typeof rawAuthor === 'string' ? rawAuthor.trim() : '';

    if (!storyTitleValue) {
      setFormError('Please provide a story or saga title.');
      return;
    }

    if (!storyAuthorValue) {
      setFormError('Please provide an author name.');
      return;
    }

    const payload = {
      project_id: projectId,
      type,
      params: {
        storyTitle: storyTitleValue,
        storyAuthor: storyAuthorValue,
        story_title: storyTitleValue,
        story_author: storyAuthorValue,
      },
      storyTitle: storyTitleValue,
      storyAuthor: storyAuthorValue,
    };

    if (type === 'generate_story') {
      if (!seedValue.trim()) {
        setFormError('Please provide a seed value.');
        return;
      }
      const seed = seedValue.trim();
      payload.seed = seed;
      payload.params.seed = seed;
    }

    if (type === 'generate_saga') {
      if (!sagaTheme.trim()) {
        setFormError('Please provide a saga theme.');
        return;
      }

      const chapters = Number(sagaChapters);
      if (!Number.isFinite(chapters) || chapters <= 0) {
        setFormError('Chapter count must be a positive number.');
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

  const handleFileChange = (event) => {
    const filesList = event.target.files;
    const filesArray = filesList ? Array.from(filesList) : [];
    setSelectedFiles(filesArray);
    setImportError(null);
    setImportMessage(null);
  };

  const handleUpload = async (event) => {
    if (event && typeof event.preventDefault === 'function') {
      event.preventDefault();
    }

    setImportError(null);
    setImportMessage(null);

    if (!selectedFiles || selectedFiles.length === 0) {
      setImportError('Vyberte prosím alespoň jeden soubor k importu.');
      return;
    }

    const formData = new FormData();
    selectedFiles.forEach((file) => {
      formData.append('files', file);
    });

    setIsImporting(true);

    try {
      const response = await importStories(projectId, formData);
      const detail = response?.data?.message || 'Soubory nahrány, zpracování spuštěno.';
      setImportMessage(detail);
      setSelectedFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (error) {
      const detail = error.response?.data?.detail || 'Nahrávání souborů se nezdařilo.';
      setImportError(detail);
    } finally {
      setIsImporting(false);
    }
  };

  return (
    <div className="project-dashboard">
      <header className="project-dashboard__header">
        <div>
          <h1>
            Project: {headingProjectName} (ID: {projectId})
          </h1>
          <p className="project-dashboard__subtitle">
            Manage tasks for <strong>{resolvedProjectName}</strong>, submit new requests, and monitor their progress in real time.
          </p>
          {estimatedTokens && (
            <p className="project-dashboard__meta">
              <strong>Estimated universe tokens:</strong> {estimatedTokens}
            </p>
          )}
        </div>
        <div className="project-dashboard__actions" aria-live="polite">
          {syncError && (
            <p className="project-dashboard__alert project-dashboard__alert--error">{syncError}</p>
          )}
          {syncMessage && (
            <p className="project-dashboard__alert project-dashboard__alert--success">{syncMessage}</p>
          )}
          {resetError && (
            <p className="project-dashboard__alert project-dashboard__alert--error">{resetError}</p>
          )}
          {resetMessage && (
            <p className="project-dashboard__alert project-dashboard__alert--success">{resetMessage}</p>
          )}
          <button
            type="button"
            className="project-dashboard__settings-button"
            onClick={openProjectSettings}
          >
            Configure AI Models
          </button>
          <button
            type="button"
            className="project-dashboard__sync-button"
            onClick={handleSynchroniseRepository}
            disabled={isSyncing}
          >
            {isSyncing ? 'Synchronising…' : 'Synchronise with Server'}
          </button>
          <button
            type="button"
            className="project-dashboard__reset-button"
            onClick={handleResetUniverse}
            disabled={isResetting}
          >
            {isResetting ? 'Resetting…' : 'Reset Universe'}
          </button>
        </div>
      </header>

      <div className="project-dashboard__layout">
        <aside className="project-dashboard__panel project-dashboard__panel--control task-forms" aria-label="Control panel">
          <h2>New Task</h2>
          {formError && <div className="task-forms__alert task-forms__alert--error">{formError}</div>}
          {formMessage && <div className="task-forms__alert task-forms__alert--success">{formMessage}</div>}

          <details className="task-forms__section" open>
            <summary className="task-forms__summary">
              <h3>Create Saga</h3>
            </summary>
            <form className="task-form" onSubmit={(event) => handleSubmit(event, 'generate_saga')}>
              <label className="task-form__label" htmlFor="saga-title">
                Story/Saga Title
              </label>
              <input
                id="saga-title"
                type="text"
                name="storyTitle"
                className="task-form__input"
                value={sagaTitle}
                onChange={(event) => setSagaTitle(event.target.value)}
                placeholder="e.g. Rise of the Machine Empire"
                required
              />
              <label className="task-form__label" htmlFor="saga-author">
                Author
              </label>
              <input
                id="saga-author"
                type="text"
                name="storyAuthor"
                className="task-form__input"
                value={sagaAuthor}
                onChange={(event) => setSagaAuthor(event.target.value)}
                placeholder="e.g. eLKA User"
                required
              />
              <label className="task-form__label" htmlFor="saga-theme">
                Saga theme
              </label>
              <textarea
                id="saga-theme"
                name="theme"
                className="task-form__textarea"
                rows={3}
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
                name="chapters"
                className="task-form__input"
                value={sagaChapters}
                onChange={(event) => setSagaChapters(event.target.value)}
              />
              <button type="submit" className="task-form__submit" disabled={isSubmitting}>
                {isSubmitting ? 'Submitting…' : 'Submit'}
              </button>
            </form>
          </details>

          <details className="task-forms__section">
            <summary className="task-forms__summary">
              <h3>Generate Story</h3>
            </summary>
            <form className="task-form" onSubmit={(event) => handleSubmit(event, 'generate_story')}>
              <label className="task-form__label" htmlFor="story-title">
                Story/Saga Title
              </label>
              <input
                id="story-title"
                type="text"
                name="storyTitle"
                className="task-form__input"
                value={storyTitle}
                onChange={(event) => setStoryTitle(event.target.value)}
                placeholder="e.g. Chronicles of Avalon"
                required
              />
              <label className="task-form__label" htmlFor="story-author">
                Author
              </label>
              <input
                id="story-author"
                type="text"
                name="storyAuthor"
                className="task-form__input"
                value={storyAuthor}
                onChange={(event) => setStoryAuthor(event.target.value)}
                placeholder="e.g. eLKA User"
                required
              />
              <label className="task-form__label" htmlFor="seed-value">
                Seed
              </label>
              <input
                id="seed-value"
                type="text"
                name="seed"
                className="task-form__input"
                value={seedValue}
                onChange={(event) => setSeedValue(event.target.value)}
                placeholder="e.g. a hidden library in the mountains"
              />
              <button type="submit" className="task-form__submit" disabled={isSubmitting}>
                {isSubmitting ? 'Submitting…' : 'Submit'}
              </button>
            </form>
          </details>

          <details className="task-forms__section">
            <summary className="task-forms__summary">
              <h3>Process Existing Story</h3>
            </summary>
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
          </details>

          <details className="task-forms__section">
            <summary className="task-forms__summary">
              <h3>Hromadný import příběhů</h3>
            </summary>
            <form className="task-form">
              <label className="task-form__label" htmlFor="bulk-import-files">
                Vyberte soubory (.txt nebo .md)
              </label>
              <input
                id="bulk-import-files"
                ref={fileInputRef}
                type="file"
                multiple
                accept=".txt,.md"
                className="task-form__input"
                onChange={handleFileChange}
              />
              {selectedFiles.length > 0 && (
                <p style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: '#475569' }}>
                  {selectedFiles.length === 1
                    ? `${selectedFiles[0].name} připraven k importu.`
                    : `${selectedFiles.length} souborů připraveno k importu.`}
                </p>
              )}
              {importError && (
                <div className="task-forms__alert task-forms__alert--error">{importError}</div>
              )}
              {importMessage && (
                <div className="task-forms__alert task-forms__alert--success">{importMessage}</div>
              )}
              <button
                type="button"
                className="task-form__submit"
                onClick={handleUpload}
                disabled={isImporting}
              >
                {isImporting ? 'Nahrávám…' : 'Nahrát a zpracovat soubory'}
              </button>
            </form>
          </details>
        </aside>

        <section className="project-dashboard__panel project-dashboard__panel--queue task-queue" aria-label="Task queue">
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
              {topLevelTasks.map((task) => (
                <TaskItem
                  key={task.id}
                  task={task}
                  allTasks={sortedTasks}
                  isTaskExpanded={isTaskExpanded}
                  toggleTaskExpansion={toggleTaskExpansion}
                  getProgressValue={getProgressValue}
                  handleTaskAction={handleTaskAction}
                  handleApproveTask={handleApproveTask}
                  handleDeleteTask={handleDeleteTask}
                  isPendingAction={isPendingAction}
                  openStoryModal={openStoryModal}
                  openFilesModal={openFilesModal}
                />
              ))}
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

              {modalContent.type === 'project-settings' && (
                <ProjectSettings
                  projectId={modalContent.data?.projectId}
                  onClose={closeModal}
                />
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
