export type FunctionBridgeKind = 'entry' | 'controller' | 'handler';

export interface FunctionRouteInfo {
  path: string;
  methods?: string[];
  source?: string;
}

export interface FunctionBridgeInfo {
  adapterId: string;
  framework: string;
  kind: FunctionBridgeKind;
  reason?: string;
}

export function formatFunctionRouteLabel(route?: FunctionRouteInfo | null) {
  if (!route?.path) {
    return '';
  }

  const methods = route.methods?.filter(Boolean) || [];
  if (!methods.length) {
    return route.path;
  }

  return `[${methods.join('/')}] ${route.path}`;
}
