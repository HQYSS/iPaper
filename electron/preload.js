// Preload script
// 用于在渲染进程中暴露安全的 API

const { contextBridge, ipcRenderer } = require('electron')

// 暴露给前端的 API
contextBridge.exposeInMainWorld('electronAPI', {
  // 平台信息
  platform: process.platform,
  
  // 版本信息
  versions: {
    node: process.versions.node,
    chrome: process.versions.chrome,
    electron: process.versions.electron
  },

  // 检查是否在 Electron 环境中运行
  isElectron: true,

  // 未来可以在这里添加更多的 IPC 通信方法
  // 例如：
  // openFile: () => ipcRenderer.invoke('dialog:openFile'),
  // saveFile: (content) => ipcRenderer.invoke('dialog:saveFile', content),
  // showNotification: (title, body) => ipcRenderer.send('show-notification', { title, body }),
})

// 在控制台打印环境信息（开发时有用）
console.log('iPaper Electron Preload Script Loaded')
console.log('Platform:', process.platform)
console.log('Electron:', process.versions.electron)
