import { useState } from "react";
import { LoginScreen } from "./components/LoginScreen";
import { ChatInterface } from "./components/ChatInterface";

function App() {
  const [username, setUsername] = useState(null);

  if (!username) {
    return <LoginScreen onLogin={setUsername} />;
  }

  return (
    <ChatInterface username={username} onLogout={() => setUsername(null)} />
  );
}

export default App;
