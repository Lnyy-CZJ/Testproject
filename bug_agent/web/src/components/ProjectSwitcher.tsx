import { logger } from '../utils/logger';
import React, { useState, useEffect, useCallback } from 'react';
import { Select, Space, Tag } from 'antd';
import { FolderOutlined, CalendarOutlined } from '@ant-design/icons';
import { appStorage } from '../utils/storage';
import { useNavigate, useLocation } from 'react-router-dom';
import { listProjects, listIterations } from '../api';
import type { Project, Iteration } from '../types';

type ProjectPick = Pick<Project, 'id' | 'name' | 'code'>;
type IterationPick = Pick<Iteration, 'id' | 'name'> & { status?: string };

interface ProjectSwitcherProps {
  showIteration?: boolean;
}

function normalizeIterations(payload: unknown): Iteration[] {
  if (Array.isArray(payload)) {
    return payload as Iteration[];
  }
  if (payload && typeof payload === 'object') {
    const record = payload as { items?: unknown; list?: unknown; iterations?: unknown };
    if (Array.isArray(record.items)) {
      return record.items as Iteration[];
    }
    if (Array.isArray(record.list)) {
      return record.list as Iteration[];
    }
    if (Array.isArray(record.iterations)) {
      return record.iterations as Iteration[];
    }
  }
  return [];
}

const ProjectSwitcher: React.FC<ProjectSwitcherProps> = ({ showIteration = true }) => {
  const navigate = useNavigate();
  const location = useLocation();
  
  const [projects, setProjects] = useState<Project[]>([]);
  const [iterations, setIterations] = useState<Iteration[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>('');
  const [selectedIteration, setSelectedIteration] = useState<string>('');
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingIterations, setLoadingIterations] = useState(false);

  useEffect(() => {
    const fetchProjects = async () => {
      setLoadingProjects(true);
      try {
        const res = await listProjects({ page: 1, pageSize: 100 });
        setProjects(res.data?.items || []);
      } catch (error) {
        logger.error('Failed to fetch projects:', error);
      } finally {
        setLoadingProjects(false);
      }
    };

    const loadLastSelection = () => {
      const lastProjectId = localStorage.getItem('lastProjectId');
      if (lastProjectId) {
        setSelectedProject(lastProjectId);
        const lastIterationId = localStorage.getItem('lastIterationId');
        if (lastIterationId) {
          setSelectedIteration(lastIterationId);
        }
      }
    };

    void fetchProjects();
    loadLastSelection();
  }, []);

  useEffect(() => {
    const match = location.pathname.match(/^\/projects\/(\d+)/);
    if (match?.[1] && match[1] !== selectedProject) {
      setSelectedProject(match[1]);
      localStorage.setItem('lastProjectId', match[1]);
    }
  }, [location.pathname, selectedProject]);

  const fetchIterations = useCallback(async (projectId: number) => {
    setLoadingIterations(true);
    try {
      const res = await listIterations(projectId);
      setIterations(normalizeIterations(res.data));
    } catch (error) {
      logger.error('Failed to fetch iterations:', error);
      setIterations([]);
    } finally {
      setLoadingIterations(false);
    }
  }, []);

  useEffect(() => {
    if (selectedProject) {
      fetchIterations(Number(selectedProject));
    }
  }, [selectedProject, fetchIterations]);

  useEffect(() => {
    const onIterationsUpdated = () => {
      if (selectedProject) {
        fetchIterations(Number(selectedProject));
      }
    };
    window.addEventListener('project-iterations-updated', onIterationsUpdated);
    return () => window.removeEventListener('project-iterations-updated', onIterationsUpdated);
  }, [selectedProject, fetchIterations]);

  const handleProjectChange = (value: string) => {
    setSelectedProject(value);
    setSelectedIteration('');
    localStorage.setItem('lastProjectId', value);
    localStorage.removeItem('lastIterationId');
    navigate(`/projects/${value}`);
  };

  const handleIterationChange = (value: string) => {
    setSelectedIteration(value);
    localStorage.setItem('lastIterationId', value);
  };

  return (
    <Space size={16} style={{ display: 'flex', alignItems: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <FolderOutlined style={{ color: '#a855f7' }} />
        <span style={{ fontSize: 13, fontWeight: 500, color: '#475569' }}>项目:</span>
        <Select
          value={selectedProject}
          onChange={handleProjectChange}
          placeholder="选择项目"
          loading={loadingProjects}
          style={{ width: 200 }}
          showSearch
          optionFilterProp="label"
        >
          {projects.map(p => (
            <Select.Option key={p.id} value={String(p.id)} label={p.name}>
              {p.code} - {p.name}
            </Select.Option>
          ))}
        </Select>
      </div>

      {showIteration && selectedProject && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <CalendarOutlined style={{ color: '#0ea5e9' }} />
          <span style={{ fontSize: 13, fontWeight: 500, color: '#475569' }}>迭代:</span>
          <Select
            value={selectedIteration || undefined}
            onChange={handleIterationChange}
            placeholder="全部迭代"
            loading={loadingIterations}
            style={{ width: 180 }}
            allowClear
            showSearch
            optionFilterProp="label"
          >
            {iterations.map(it => (
              <Select.Option key={it.id} value={String(it.id)} label={it.name}>
                <Space size={4}>
                  {it.status === 'active' && <Tag color="processing" style={{ fontSize: 10, margin: 0 }}>进行中</Tag>}
                  {it.status === 'completed' && <Tag color="success" style={{ fontSize: 10, margin: 0 }}>已完成</Tag>}
                  {it.name}
                </Space>
              </Select.Option>
            ))}
          </Select>
        </div>
      )}
    </Space>
  );
};

export default ProjectSwitcher;
