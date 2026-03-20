import { createLocalProjectDataSource, type ProjectDataSource } from './projectDataSource';

const sessionStore = new Map<string, ProjectDataSource>();

function createSessionId() {
  return `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createLocalProjectSession(files: File[]) {
  const sessionId = createSessionId();
  const dataSource = createLocalProjectDataSource(files, { sessionKey: sessionId });
  sessionStore.set(sessionId, dataSource);
  return {
    sessionId,
    dataSource,
  };
}

export function getLocalProjectSession(sessionId: string) {
  return sessionStore.get(sessionId) || null;
}
