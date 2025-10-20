import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  fetchUniverseFileContent,
  fetchUniverseFiles,
} from '../services/api';
import './UniverseBrowserPage.css';

const UniverseBrowserPage = () => {
  const { projectId } = useParams();
  const [tree, setTree] = useState([]);
  const [treeError, setTreeError] = useState(null);
  const [isTreeLoading, setIsTreeLoading] = useState(false);
  const [expandedPaths, setExpandedPaths] = useState([]);
  const [selectedFilePath, setSelectedFilePath] = useState(null);
  const [selectedFileContent, setSelectedFileContent] = useState('');
  const [isContentLoading, setIsContentLoading] = useState(false);
  const [contentError, setContentError] = useState(null);

  const normalisedProjectId = useMemo(() => projectId ?? '', [projectId]);

  const toggleFolder = useCallback((path) => {
    setExpandedPaths((previous) =>
      previous.includes(path)
        ? previous.filter((current) => current !== path)
        : [...previous, path],
    );
  }, []);

  const loadTree = useCallback(async () => {
    if (!normalisedProjectId) {
      return;
    }

    setIsTreeLoading(true);
    setTreeError(null);

    try {
      const data = await fetchUniverseFiles(normalisedProjectId);
      setTree(Array.isArray(data) ? data : []);
    } catch (error) {
      const detail = error?.response?.data?.detail;
      setTree([]);
      setTreeError(detail || 'Failed to load project files.');
    } finally {
      setIsTreeLoading(false);
    }
  }, [normalisedProjectId]);

  const loadFileContent = useCallback(
    async (path) => {
      if (!normalisedProjectId || !path) {
        return;
      }

      setIsContentLoading(true);
      setContentError(null);

      try {
        const response = await fetchUniverseFileContent(normalisedProjectId, path);
        const content = typeof response?.content === 'string' ? response.content : '';
        setSelectedFileContent(content);
      } catch (error) {
        const detail = error?.response?.data?.detail;
        setSelectedFileContent('');
        setContentError(detail || 'Failed to load the selected file.');
      } finally {
        setIsContentLoading(false);
      }
    },
    [normalisedProjectId],
  );

  useEffect(() => {
    setExpandedPaths([]);
    setSelectedFilePath(null);
    setSelectedFileContent('');
    setContentError(null);
    void loadTree();
  }, [normalisedProjectId, loadTree]);

  const handleFileSelect = useCallback(
    (path) => {
      setSelectedFilePath(path);
      void loadFileContent(path);
    },
    [loadFileContent],
  );

  const renderTree = useCallback(
    (nodes, parentPath = '') => {
      if (!Array.isArray(nodes) || nodes.length === 0) {
        return null;
      }

      return (
        <ul className="file-tree__list">
          {nodes.map((node) => {
            const basePath = parentPath ? `${parentPath}/${node.name}` : node.name;
            if (node.type === 'folder') {
              const isExpanded = expandedPaths.includes(basePath);
              return (
                <li key={`folder-${basePath}`} className="file-tree__item">
                  <button
                    type="button"
                    className={`file-tree__button file-tree__button--folder${isExpanded ? ' expanded' : ''}`}
                    onClick={() => toggleFolder(basePath)}
                    aria-expanded={isExpanded}
                  >
                    <span aria-hidden className="file-tree__icon">
                      {isExpanded ? '📂' : '📁'}
                    </span>
                    {node.name}
                  </button>
                  {isExpanded ? renderTree(node.children || [], basePath) : null}
                </li>
              );
            }

            if (node.type === 'file' && typeof node.path === 'string') {
              const isActive = selectedFilePath === node.path;
              return (
                <li key={`file-${node.path}`} className="file-tree__item">
                  <button
                    type="button"
                    className={`file-tree__button file-tree__button--file${isActive ? ' active' : ''}`}
                    onClick={() => handleFileSelect(node.path)}
                  >
                    <span aria-hidden className="file-tree__icon">📄</span>
                    {node.name}
                  </button>
                </li>
              );
            }

            return null;
          })}
        </ul>
      );
    },
    [expandedPaths, handleFileSelect, selectedFilePath, toggleFolder],
  );

  return (
    <div className="browser" aria-live="polite">
      <section className="browser__panel browser__panel--tree">
        <header className="browser__panel-header">
          <h2>Universe files</h2>
          <button
            type="button"
            className="browser__refresh"
            onClick={() => void loadTree()}
            disabled={isTreeLoading}
          >
            Refresh
          </button>
        </header>
        <div className="browser__panel-body">
          {isTreeLoading ? (
            <p className="browser__status">Loading files…</p>
          ) : treeError ? (
            <p className="browser__status browser__status--error">{treeError}</p>
          ) : tree.length === 0 ? (
            <p className="browser__status">No files found in this project.</p>
          ) : (
            <nav className="file-tree" aria-label="Project file tree">
              {renderTree(tree)}
            </nav>
          )}
        </div>
      </section>
      <section className="browser__panel browser__panel--content">
        <header className="browser__panel-header">
          <h2>{selectedFilePath || 'Select a file to preview'}</h2>
        </header>
        <div className="browser__panel-body browser__panel-body--content">
          {isContentLoading ? (
            <p className="browser__status">Loading file…</p>
          ) : contentError ? (
            <p className="browser__status browser__status--error">{contentError}</p>
          ) : selectedFilePath ? (
            <pre className="browser__code" tabIndex={0}>
              {selectedFileContent || 'The file is empty.'}
            </pre>
          ) : (
            <p className="browser__status">Choose a file from the tree to view its contents.</p>
          )}
        </div>
      </section>
    </div>
  );
};

export default UniverseBrowserPage;
