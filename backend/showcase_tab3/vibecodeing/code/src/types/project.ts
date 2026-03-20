export type ProjectSourceType = 'github' | 'local';

export interface ProjectFile {
  path: string;
  mode?: string;
  type: 'blob' | 'tree';
  sha?: string;
  size?: number;
  url?: string;
}

export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'folder';
  children?: FileNode[];
  isOpen?: boolean;
}

export interface ProjectDataSourceDescriptor {
  type: ProjectSourceType;
  key: string;
  projectName: string;
  fullName: string;
  location: string;
  owner?: string;
  repo?: string;
}
