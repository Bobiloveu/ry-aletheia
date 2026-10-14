// Presentation only: the controller and actual bitmap/pose decide completion.
export function relocalizationProgressState({ phase, pending, switchingMap, waitingMap, awaitingPose }) {
  if (!switchingMap && !waitingMap && !awaitingPose) return null;
  if (phase === 'failed') return {
    state: 'failed', title: '切图或重定位未完成',
    detail: '车辆保持停车，请在手动重定位面板中查看原因并处理。',
  };
  if (pending && switchingMap) return {
    state: 'busy', title: '正在切换地图与重定位',
    detail: '正在加载目标地图并初始化定位，车辆保持停车。',
  };
  if (phase === 'unavailable') return {
    state: 'unknown', title: '等待操作状态确认',
    detail: '连接暂未确认，请保持停车并查看手动重定位面板。',
  };
  if (waitingMap) return {
    state: 'busy', title: '正在加载目标地图',
    detail: '定位已确认，等待新底图就绪。',
  };
  return {
    state: 'busy', title: '等待实时位姿',
    detail: '定位已确认，正在接收新的车体位置。',
  };
}
