export type RegionBox = { x: number; y: number; width: number; height: number };
export type RegionFrame = {
  source_id: string; source_time: number; frame_width: number; frame_height: number; image_data_url: string;
};
export type RegionResult = {
  track_id: string;
  track: {status: string; stop_time: number | null; frame_width: number; frame_height: number;
    samples: {source_time: number; center_x_px: number; center_y_px: number}[]};
};

export type TwoPinResult = {
  track_id: string;
  track: {status: string; stop_time: number | null; frame_width: number; frame_height: number;
    initial_distance_px: number | null; initial_vector_x_px: number | null; initial_vector_y_px: number | null;
    pin_a_status: string; pin_b_status: string;
    samples: {source_time: number; position_x_px: number; position_y_px: number;
      pin_b_x_px: number; pin_b_y_px: number; rotation_deg: number; scale_percent: number}[]};
};

export function isRegionFrame(value: RegionFrame, source: string) {
  return value.source_id === source && Number.isFinite(value.source_time) &&
    Number.isInteger(value.frame_width) && value.frame_width > 0 &&
    Number.isInteger(value.frame_height) && value.frame_height > 0 &&
    /^data:image\/(png|jpeg|webp);base64,/.test(value.image_data_url);
}
