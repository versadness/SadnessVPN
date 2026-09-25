// Read only state; optional graceful close only if no active VPN or Zapret.
const socket = new WebSocket('ws://127.0.0.1:45678/ws');
const timeout = setTimeout(() => {socket.close();process.exitCode=1;}, 5000);
socket.onmessage = async event => {
  const state = JSON.parse(event.data);
  if(state.type !== 'state')return;
  clearTimeout(timeout);
  console.log(JSON.stringify({version:state.appVersion,status:state.status,connected:state.connected,zapretRunning:state.zapretRunning}));
  socket.close();
  if(process.argv.includes('--close-idle')){
    if(state.status!=='off'||state.connected||state.zapretRunning)throw Error('Active connection: refusing close');
    // Бэкенд сам проверяет, что VPN и Zapret выключены, и просит Electron выйти.
    const reply=await fetch('http://127.0.0.1:45678/api/updates/close-for-recovery',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    console.log('Graceful close: '+reply.status);
  }
};
socket.onerror=()=>{clearTimeout(timeout);process.exitCode=1;};
