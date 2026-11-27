const { contextBridge, ipcRenderer } = require('electron');
const methods = ["health","capabilities","modelStatus","modelTest","modelConfigure","modelForgetSaved","conversations","conversationCreate","conversationGet","conversationUpdate","conversationDelete","messages","send","confirmGrowth","cancelGrowth","goals","goal","previewGrowth","applyGrowth","cancelPreview","memories","forgetMemory","allowMemory","claims","claim","backgroundStatus","backgroundJobs","exportData","clearData"];
contextBridge.exposeInMainWorld('becoming', Object.freeze(Object.fromEntries(
  methods.map(name => [name, (...args) => ipcRenderer.invoke('becoming:' + name, ...args)])
)));
