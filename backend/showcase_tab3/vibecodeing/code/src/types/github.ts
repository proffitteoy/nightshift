import type { FileNode, ProjectFile } from './project';

export type GithubFile = ProjectFile;

export interface GithubTreeResponse {
  sha: string;
  url: string;
  tree: GithubFile[];
  truncated: boolean;
}

export type { FileNode };
