declare module "@jellybrick/dbus-next" {
  interface ClientInterface {
    GetManagedObjects(): Promise<Record<string, Record<string, Record<string, { value?: unknown }>>>>;
  }

  interface ProxyObject {
    getInterface(name: string): ClientInterface;
  }

  interface MessageBus {
    getProxyObject(name: string, path: string): Promise<ProxyObject>;
    disconnect(): void;
  }

  const dbus: {
    systemBus(): MessageBus;
  };

  export default dbus;
}
