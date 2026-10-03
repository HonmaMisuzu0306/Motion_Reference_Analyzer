import { it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { PreviewPanel } from './PreviewPanel';
it('再次选择同镜头仍暂停并跳回起点', () => {
  const pause=vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
  const props={source:'video',seekRequest:{time:4.25,sequence:1},onTimeChange:vi.fn()};
  const view=render(<PreviewPanel {...props}/>);
  const video=view.container.querySelector('video')!;
  Object.defineProperty(video,'readyState',{value:4,configurable:true});
  fireEvent.loadedMetadata(video);
  video.currentTime=4.33;
  view.rerender(<PreviewPanel {...props} seekRequest={{time:4.25,sequence:2}}/>);
  expect(video.currentTime).toBe(4.25);
  expect(pause).toHaveBeenCalled();
  pause.mockRestore();
});

it('片段播放到出点暂停，普通镜头跳转可离开选区',()=>{
 const pause=vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
 const play=vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue();
 const props={source:'video',seekRequest:{time:10,sequence:1},onTimeChange:vi.fn(),playRange:{start:10,end:13.5,sequence:1}};
 const view=render(<PreviewPanel {...props}/>);const video=view.container.querySelector('video')!;
 Object.defineProperty(video,'readyState',{value:4,configurable:true});fireEvent.loadedMetadata(video);
 video.currentTime=13.6;fireEvent.timeUpdate(video);
 expect(video.currentTime).toBe(13.5);expect(pause).toHaveBeenCalled();
 view.rerender(<PreviewPanel {...props} playRange={null} seekRequest={{time:18,sequence:2}}/>);
 expect(video.currentTime).toBe(18);
 pause.mockRestore();play.mockRestore();
});

it('原生拖动到选区外退出片段限制，结束后可普通播放',()=>{
 const pause=vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
 const play=vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue();
 const exit=vi.fn();
 const view=render(<PreviewPanel source="video" seekRequest={{time:0,sequence:0}} onTimeChange={()=>{}} playRange={{start:1,end:2,sequence:1}} onRangeExit={exit}/>);
 const video=view.container.querySelector('video')!;
 Object.defineProperty(video,'readyState',{value:4,configurable:true});fireEvent.loadedMetadata(video);fireEvent.seeked(video);
 video.currentTime=5;fireEvent.seeking(video);fireEvent.timeUpdate(video);
 expect(video.currentTime).toBe(5);expect(exit).toHaveBeenCalledTimes(1);
 fireEvent.play(video);video.currentTime=6;fireEvent.timeUpdate(video);expect(video.currentTime).toBe(6);
 pause.mockRestore();play.mockRestore();
});
