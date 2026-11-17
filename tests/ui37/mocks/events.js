/**
 * Stand-in for DWC 3.7's `@/utils/events` mitt emitter.
 *
 * Only the three methods our entry point uses are implemented.
 */
const handlers = new Map();


const Events = {
  on(event, handler) {
    if (!handlers.has(event)) {
      handlers.set(event, new Set());
    }
    handlers.get(event).add(handler);
  },
  off(event, handler) {
    handlers.get(event)?.delete(handler);
  },
  emit(event, payload) {
    for (const handler of [...(handlers.get(event) ?? [])]) {
      handler(payload);
    }
  },
  /** Test-only: forget every registration between cases. */
  reset() {
    handlers.clear();
  },
  handlerCount(event) {
    return handlers.get(event)?.size ?? 0;
  },
};

export default Events;
