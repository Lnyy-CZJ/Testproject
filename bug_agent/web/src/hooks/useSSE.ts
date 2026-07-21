import { useEffect, useRef, useState, useCallback } from 'react';
import { sseManager } from './sseManager';
import { appStorage } from '../utils/storage';

export function useSSE(rooms: string[]): { connected: boolean } {
  const [connected, setConnected] = useState(sseManager.isConnected());
  const roomsRef = useRef(rooms);

  useEffect(() => {
    roomsRef.current = rooms;
  }, [rooms]);

  useEffect(() => {
    const unsubscribe = sseManager.onConnectionChange(setConnected);
    return unsubscribe;
  }, []);

  const connect = useCallback(() => {
    const token = appStorage.getToken();
    if (token && roomsRef.current.length > 0) {
      sseManager.connect(token, roomsRef.current);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      sseManager.disconnect();
    };
  }, [connect]);

  return { connected };
}

export function useSSEEvent(event: string, handler: (data: any) => void): void {
  const handlerRef = useRef(handler);

  useEffect(() => {
    handlerRef.current = handler;
  });

  useEffect(() => {
    const stableHandler = (data: any) => handlerRef.current(data);
    sseManager.on(event, stableHandler);
    return () => {
      sseManager.off(event, stableHandler);
    };
  }, [event]);
}
