import type { MessageInstance } from 'antd/es/message/interface';
import { message as staticMessage } from 'antd';

let currentMessage: MessageInstance | null = null;

export function setMessageInstance(instance: MessageInstance) {
  currentMessage = instance;
}

type MessageType = typeof staticMessage;

export const message: MessageType = new Proxy(staticMessage as MessageType, {
  get(target, prop, receiver) {
    const active = currentMessage ?? target;
    const value = Reflect.get(active as object, prop, receiver);
    if (typeof value === 'function') {
      return value.bind(active);
    }
    return value;
  },
});
