const values:Record<string,string>={weak:'弱',strong:'强',low:'低',medium:'中等',high:'高',insufficient_features:'特征点不足',not_analyzed:'尚未分析',failed:'失败',no_frames:'缺少帧',unknown:'无法判断',static:'静止',zoom_in:'推近',push_in:'推近',zoom_out:'拉远',pull_out:'拉远',pan_left:'向左平移',pan_right:'向右平移',tilt_up:'向上移动',tilt_down:'向下移动',shake:'抖动',rotation:'旋转',complex:'复杂变化',character:'角色',object:'物体',text:'文字',mixed:'混合',center:'居中',left:'左侧',right:'右侧',top:'上方',bottom:'下方',top_left:'左上',top_right:'右上',bottom_left:'左下',bottom_right:'右下',solid:'纯色',photo:'照片',illustration:'插画',gradient:'渐变',title:'标题',subtitle:'副标题',lyrics:'歌词',dialogue:'对白',character_name:'角色名',decorative:'装饰',narrative:'叙述',credit:'署名',logo_like:'标识',serif:'衬线',sans_serif:'无衬线',display:'展示字体',handwritten_like:'手写风格',thin:'细',regular:'常规',bold:'粗',tight:'紧凑',normal:'常规',wide:'宽',horizontal:'横排',vertical:'竖排',white:'白色',black:'黑色',red:'红色',blue:'蓝色',warm:'暖色',cool:'冷色',glow:'辉光',bloom:'泛光',blur:'模糊',chromatic_aberration:'色差',noise:'噪点',grain:'颗粒',vignette:'暗角',particles:'粒子',light_leak:'漏光',outline:'轮廓',shadow:'阴影',stroke:'描边',none:'无',slide_left:'向左滑动',slide_right:'向右滑动',slide_up:'向上滑动',slide_down:'向下滑动',scale_in:'放大进入',scale_out:'缩小退出',fade:'淡入淡出',fade_in:'淡入',fade_out:'淡出',ja:'日语',zh:'中文',en:'英语',japan:'日语',ch:'中文',ok:'正常',error:'异常',unavailable:'不可用',insufficient:'数据不足',reliable:'可靠',unreliable:'不可靠',success:'成功',easy:'简单',hard:'较难',position:'位置',scale:'缩放',opacity:'不透明度',foreground:'前景',background:'背景',subject:'主体',camera:'相机',semantic:'AI解读',measured:'运动测量',summary:'综合提示',pending:'尚未处理',skipped:'已省略',completed:'已完成'};
Object.assign(values,{typography:'文字排版',depth:'景深层次',global_scale:'整体缩放',character_scale:'主体缩放',position_x:'水平位置',position_y:'垂直位置'});
Object.assign(values,{light:'轻微'});
export function formatRecipeNumber(value:unknown):string{
 if(typeof value!=='number')return String(value??'暂无');
 if(!Number.isFinite(value))return '不可用';
 if(value!==0&&(Math.abs(value)>=1e6||Math.abs(value)<.01))return value.toExponential(2);
 return String(Number(value.toFixed(2)));
}
export function formatRecipeRange(value:unknown):string|null{
 if(value===null||typeof value!=='object'||Array.isArray(value))return null;
 const {min_value:min,max_value:max,unit}=value as Record<string,unknown>;
 if(typeof min!=='number'||typeof max!=='number'||!Number.isFinite(min)||!Number.isFinite(max)||min>max)return null;
 return `${formatRecipeNumber(min)}–${formatRecipeNumber(max)} ${typeof unit==='string'&&unit.trim()?unit:'单位未记录'}`;
}
export function formatSamplingRate(value: unknown): string | null {
 return typeof value === 'number' && Number.isFinite(value) && value > 0 ? `${value} 帧/秒` : null;
}
export function formatTrackingScore(value:unknown):string{
 if(value==null)return '暂无';
 return typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1?`${(value*100).toFixed(0)}/100`:'不可用';
}
export const TRACKING_SCORE_NOTE='跟踪评分综合特征匹配、有效帧对和运动平滑性，不代表测量准确率；100/100 也不表示无误差。';
export const NET_MOTION_NOTE='净位移仅表示首尾差；往返幅度请看轨迹范围。';
export function labelValue(_group:string,value:unknown):string{if(value==null||value==='')return '暂无';if(_group==='difficulty'&&/^[★☆]+$/.test(String(value)))return String(value);return values[String(value)]||`未识别（${String(value)}）`}
export function displayRecipeText(value:unknown):string{
 const text=String(value??'');
 if(!text)return '暂无';
 const fixed:Record<string,string>={'separate background layer':'独立背景图层','isolated character/object layer':'独立角色或物体图层','text layer with mask reveal':'文字图层配合蒙版显示','Approximation from measured global motion, not exact AE params.':'基于整体运动测量的近似参考，无法还原精确 AE 参数。'};
 if(fixed[text])return fixed[text];
 const measured=/^(Global scale change|Horizontal translation|Vertical translation|Rotation) measured: ([+-]?\d+(?:\.\d+)?[%°])$/.exec(text);
 if(measured){const names:Record<string,string>={'Global scale change':'整体缩放变化','Horizontal translation':'水平位移','Vertical translation':'垂直位移','Rotation':'旋转'};return `测得${names[measured[1]]}：${measured[2]}`}
 const depth=/^(\d+) depth layers for parallax$/.exec(text);
 if(depth)return `${depth[1]} 个景深图层用于视差`;
 return values[text]||text;
}
const fields:Record<string,string>={subject_type:'主体类型',subject_position:'主体位置',background_type:'背景类型',depth_layers:'层次',type:'类型',strength:'强度',confidence:'置信度',description:'描述',has_text:'包含文字',position:'位置',style:'风格',role:'用途',style_family:'字体风格',weight:'字重',tracking:'字距',alignment:'对齐',orientation:'方向',dominant_color:'主要颜色',contrast_level:'对比度',visual_emphasis:'视觉强调',motion_style:'文字运动',observations:'画面观察',ae_hypothesis:'AE实现推测',possible_method:'可能方法',possible_effect:'可能效果',possible_transition:'可能转场',notes:'备注',semantic:'AI解读',measured:'运动测量',summary:'综合提示',scale:'缩放',translation_x:'水平位移',translation_y:'垂直位移',rotation_degrees:'旋转角度',status:'状态',layers:'图层建议',camera:'相机',transform:'变换建议',measured_motion:'运动测量',typography:'文字排版',effects:'效果建议',difficulty:'制作难度',hypothesis:'实现推测',suggestion:'建议',method:'测量方法',message:'说明',sample_count:'采样数',valid_pair_count:'有效帧对',total_pair_count:'帧对总数',translation_x_px:'水平位移（像素）',translation_y_px:'垂直位移（像素）',translation_x_ratio:'水平位移比例',translation_y_ratio:'垂直位移比例',scale_ratio:'缩放比例',scale_change_percent:'缩放变化（%）',rotation_deg:'旋转（度）',motion_strength:'运动强度',stability:'稳定度',shake_score:'抖动强度',cv_analysis_ms:'测量耗时（毫秒）',semantic_type:'AI运动类型',semantic_confidence:'AI置信度',measured_type:'测量运动类型',measured_confidence:'测量置信度',fused_type:'综合运动类型',fused_confidence:'综合置信度',conflict:'结果存在分歧',measured_status:'测量状态',text:'文字',start_time:'开始时间',end_time:'结束时间',duration:'时长',motion:'运动',appearance:'出现方式',estimated_size:'大小估计',suggested_animation:'动画建议',target:'目标',reason:'依据',value:'数值',unit:'单位'};
Object.assign(fields,{hold:'显示期间',in:'进入',out:'退出',opacity:'不透明度',animation_plan:'关键帧试作方案',evidence_source:'参数来源',source_start:'源视频入点（秒）',source_end:'源视频出点（秒）',time_origin:'时间基准',keyframes:'关键帧参数',property:'AE 属性',from:'起始值',to:'结束值',version:'版本',global_scale:'整体缩放',character_scale:'主体缩放',position_x:'水平位置',position_y:'垂直位置',rotation:'旋转'});
Object.assign(fields,{long_baseline_check_count:'跨帧复核区间数',long_baseline_conflict_count:'发现运动冲突的复核区间',mixed_support_pair_count:'多组运动不一致的帧对',spatially_limited_pair_count:'仅局部支持的帧对',sampling_target_fps:'目标采样率',trajectory_status:'轨迹状态',translation_reference:'平移参考',frame_width:'画面宽度（像素）',frame_height:'画面高度（像素）'});
Object.assign(fields,{translation_x_px:'净水平位移（像素）',translation_y_px:'净垂直位移（像素）',translation_x_ratio:'净水平位移比例',translation_y_ratio:'净垂直位移比例',min_value:'范围最小值',max_value:'范围最大值',measured_confidence:'跟踪评分'});
Object.assign(values,{mixed_support:'多组运动不一致',too_few_valid_pairs:'有效帧对不足',high_variance:'测量波动过大',localized_support:'跟踪点集中在局部',incomplete_tracking:'跟踪不完整',not_measured:'尚未测量轨迹',complete:'采样连续',partial:'部分跟踪',frame_center:'画面中心',legacy_top_left:'旧版画面左上角'});
export function fieldLabel(key:string){return fields[key]||key}
Object.assign(values,{not_applicable:'不适用',not_cut:'不是切镜',no_beats:'无可靠节拍'});
Object.assign(fields,{composition:'构图',color_description:'色彩描述',layer_layout:'图层布局',color_treatment:'色彩处理',visible_effects:'可见效果',basis:'依据',animation:'动画',text_layers:'文字图层',bbox:'文字位置',x:'水平位置',y:'垂直位置',width:'宽度',height:'高度',track_id:'文字编号',canonical_text:'源文字',language:'语言',average_confidence:'平均置信度',average_bbox:'文字位置',frame_count:'采样帧数',observed_notes:'观察说明',color_observation:'色彩观察',typography_analysis:'排版解读'});


export function globalTotalsUnavailable(measured: {status?: unknown; trajectory_status?: unknown; valid_pair_count?: unknown}) {
 return (typeof measured.status === 'string' && measured.status !== 'ok')
   || measured.trajectory_status === 'partial' || measured.valid_pair_count === 0;
}
