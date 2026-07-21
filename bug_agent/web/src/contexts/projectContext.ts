import { createContext, useContext } from 'react';
import type { Iteration, Project, ProjectMember } from '../types';

export interface ProjectContextType {
  project: Project | null;
  projectId: number | undefined;
  iterations: Iteration[];
  currentIteration: Iteration | null;
  members: ProjectMember[];
  refreshProject: () => Promise<void>;
  refreshIterations: () => Promise<void>;
  refreshMembers: () => Promise<void>;
}

export const ProjectContext = createContext<ProjectContextType>({
  project: null,
  projectId: undefined,
  iterations: [],
  currentIteration: null,
  members: [],
  refreshProject: async () => { throw new Error('useProject must be used within a ProjectContext.Provider'); },
  refreshIterations: async () => { throw new Error('useProject must be used within a ProjectContext.Provider'); },
  refreshMembers: async () => { throw new Error('useProject must be used within a ProjectContext.Provider'); },
});

export const useProject = () => useContext(ProjectContext);
