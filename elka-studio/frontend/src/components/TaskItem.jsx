import PropTypes from 'prop-types';

const formatTokens = (value) =>
  typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-US') : '0';

const TaskItem = ({
  task,
  allTasks,
  isTaskExpanded,
  toggleTaskExpansion,
  getProgressValue,
  handleTaskAction,
  handleApproveTask,
  handleDeleteTask,
  isPendingAction,
  openStoryModal,
  openFilesModal,
}) => {
  const progressValue = getProgressValue(task);
  const expanded = isTaskExpanded(task.id);
  const storyText = typeof task?.result?.story === 'string' ? task.result.story.trim() : '';
  const files = task?.result?.files;
  const hasStory = storyText.length > 0;
  const hasFiles = files && Object.keys(files).length > 0;
  const inputTokensDisplay = formatTokens(task?.input_tokens ?? task?.total_input_tokens);
  const outputTokensDisplay = formatTokens(task?.output_tokens ?? task?.total_output_tokens);
  const normalizedStatus = typeof task?.status === 'string' ? task.status.toLowerCase() : 'unknown';
  const showTokenSummary = task?.input_tokens != null || task?.output_tokens != null;
  const isSuccessful = typeof task?.status === 'string' && task.status.toUpperCase() === 'SUCCESS';
  const requiresApproval = Boolean(task?.result?.approval_required) && !task?.result_approved;
  const canApprove = isSuccessful && requiresApproval;

  const childTasks = (allTasks || []).filter((current) => current.parent_task_id === task.id);

  return (
    <div className="task-item">
      <article className="task-card">
        <header className="task-card__header">
          <div>
            <h3 className="task-card__title">
              {task.type || 'Unknown type'} <span className="task-card__id">#{task.id}</span>
            </h3>
            <div className="task-card__status">
              <span className={`task-status-badge status-${normalizedStatus}`}>
                {task.status || 'Unknown status'}
              </span>
            </div>
            <div className="task-card__tokens">
              <span>Input: {inputTokensDisplay}</span>
              <span>Output: {outputTokensDisplay}</span>
              {showTokenSummary && (
                <span className="task-card__token-summary">
                  Tokeny: {inputTokensDisplay} (vstup) / {outputTokensDisplay} (výstup)
                </span>
              )}
            </div>
            {task?.error && <div className="task-error">{task.error}</div>}
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
            {canApprove && (
              <button
                type="button"
                className="task-card__action task-card__action--approve"
                onClick={() => handleApproveTask(task.id)}
                disabled={isPendingAction(task.id, 'approve')}
              >
                {isPendingAction(task.id, 'approve') ? 'Approving…' : 'Approve'}
              </button>
            )}
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
              <button type="button" className="task-card__detail-action" onClick={() => openStoryModal(task)}>
                Show story
              </button>
            )}
            {hasFiles && (
              <button type="button" className="task-card__detail-action" onClick={() => openFilesModal(task)}>
                Show files
              </button>
            )}
          </div>
        )}

        {task.type === 'generate_saga' && task.saga_plan && (
          <details style={{ marginTop: '10px' }}>
            <summary>Zobrazit plán ságy</summary>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                background: '#f4f4f4',
                padding: '10px',
                borderRadius: '5px',
              }}
            >
              {task.saga_plan}
            </pre>
          </details>
        )}

        {task.type === 'generate_chapter' && task.story_content && (
          <details style={{ marginTop: '10px' }}>
            <summary>Zobrazit vygenerovaný příběh</summary>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                background: '#f4f4f4',
                padding: '10px',
                borderRadius: '5px',
              }}
            >
              {task.story_content}
            </pre>
          </details>
        )}

        {expanded && (
          <div className="task-card__log">
            {task.log ? <pre>{task.log}</pre> : <p className="task-card__log-placeholder">Log is not available yet.</p>}
          </div>
        )}
      </article>

      {childTasks.length > 0 && (
        <div className="child-tasks" style={{ marginLeft: '30px', borderLeft: '2px solid #eee', paddingLeft: '10px' }}>
          {childTasks.map((child) => (
            <TaskItem
              key={child.id}
              task={child}
              allTasks={allTasks}
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
    </div>
  );
};

TaskItem.propTypes = {
  task: PropTypes.shape({
    id: PropTypes.number.isRequired,
    type: PropTypes.string,
    status: PropTypes.string,
    result: PropTypes.object,
    result_approved: PropTypes.bool,
    input_tokens: PropTypes.number,
    output_tokens: PropTypes.number,
    total_input_tokens: PropTypes.number,
    total_output_tokens: PropTypes.number,
    parent_task_id: PropTypes.number,
    saga_plan: PropTypes.string,
    story_content: PropTypes.string,
    log: PropTypes.string,
    error: PropTypes.string,
  }).isRequired,
  allTasks: PropTypes.arrayOf(PropTypes.object).isRequired,
  isTaskExpanded: PropTypes.func.isRequired,
  toggleTaskExpansion: PropTypes.func.isRequired,
  getProgressValue: PropTypes.func.isRequired,
  handleTaskAction: PropTypes.func.isRequired,
  handleApproveTask: PropTypes.func.isRequired,
  handleDeleteTask: PropTypes.func.isRequired,
  isPendingAction: PropTypes.func.isRequired,
  openStoryModal: PropTypes.func.isRequired,
  openFilesModal: PropTypes.func.isRequired,
};

export default TaskItem;
