bl_info = {
    "name": "World Space Transform Baker",
    "author": "moteki",
    "version": (0, 2, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Tools Tab",
    "description": "Bakes the world-space transform of selected objects or bones to new empties.",
    "warning": "",
    "doc_url": "",
    "category": "Animation",
}

import bpy
import mathutils

# ------------------------------------------------------------------------
# プロパティグループ (UIの状態を保持)
# ------------------------------------------------------------------------

class DummyAnimCreatorProperties(bpy.types.PropertyGroup):
    """アドオンのプロパティを保持するためのクラス"""
    
    use_location: bpy.props.BoolProperty(
        name="Location",
        description="Copy the world space location",
        default=True
    )
    use_rotation: bpy.props.BoolProperty(
        name="Rotation",
        description="Copy the world space rotation",
        default=True
    )
    use_scale: bpy.props.BoolProperty(
        name="Scale",
        description="Copy the world space scale",
        default=True
    )
    
    rotation_type: bpy.props.EnumProperty(
        items=[
            ('CURRENT', "Current", "Use the current rotation type of the source object/armature."),
            ('EULER', "Euler", "Convert to Euler rotation."),
            ('QUATERNION', "Quaternion", "Convert to Quaternion rotation.")
        ],
        name="Rotation Type",
        description="The rotation type for the new dummy empties.",
        default='CURRENT'
    )
    
    bake_mode: bpy.props.EnumProperty(
        name="Bake Mode",
        items=[
            ('CURRENT', "Current", "Only process the current frame"),
            ('ANIMATION', "Animation", "Bake the specified frame range")
        ],
        default='CURRENT'
    )
    
    frame_start: bpy.props.IntProperty(
        name="Start Frame",
        description="Start frame for baking",
        default=1
    )
    
    frame_end: bpy.props.IntProperty(
        name="End Frame",
        description="End frame for baking",
        default=250
    )

# ------------------------------------------------------------------------
# オペレーター
# ------------------------------------------------------------------------

class WM_OT_GetSceneFrameRange(bpy.types.Operator):
    """シーンのレンダリング範囲をアドオンのフレーム範囲に設定するオペレーター"""
    bl_idname = "object.get_scene_frame_range"
    bl_label = "Get Scene Frame Range"
    bl_description = "Set start and end frames from the scene's render range"

    def execute(self, context):
        props = context.scene.dummy_anim_creator_props
        props.frame_start = context.scene.frame_start
        props.frame_end = context.scene.frame_end
        self.report({'INFO'}, f"Frame range set to {props.frame_start}-{props.frame_end}")
        return {'FINISHED'}


class WM_OT_DummyAnimCreator(bpy.types.Operator):
    """メインの処理を実行するオペレーター"""
    bl_idname = "object.dummy_anim_creator"
    bl_label = "Bake Transform" # <- 修正1: オペレーター自体の名前
    bl_description = "Creates dummy empties from selected objects or bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
            return context.selected_objects
        elif context.mode == 'POSE':
            return context.selected_pose_bones
        return False

    def execute(self, context):
        props = context.scene.dummy_anim_creator_props
        original_frame = context.scene.frame_current
        
        original_mode = context.mode
        active_obj_before_op = context.active_object
        dummies = []

        try:
            sources = self.get_sources(context)

            if original_mode == 'POSE':
                bpy.ops.object.mode_set(mode='OBJECT')

            dummies = self.create_dummies(context, sources)
            
            if original_mode == 'POSE':
                context.view_layer.objects.active = active_obj_before_op
                bpy.ops.object.mode_set(mode='POSE')

            source_dummy_pairs = list(zip(sources, dummies))

            if props.bake_mode == 'CURRENT':
                self.process_single_frame(context, source_dummy_pairs)
            else:
                self.process_animation(context, source_dummy_pairs)
            
            self.report({'INFO'}, "Dummy empties created successfully.")
        
        finally:
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            bpy.ops.object.select_all(action='DESELECT')
            if dummies:
                for dummy in dummies:
                    dummy.select_set(True)
                context.view_layer.objects.active = dummies[0]

            context.scene.frame_set(original_frame)

            if original_mode == 'POSE' and active_obj_before_op:
                context.view_layer.objects.active = active_obj_before_op
                bpy.ops.object.mode_set(mode='POSE')

        return {'FINISHED'}

    def get_sources(self, context):
        sources = []
        if context.mode == 'OBJECT':
            for obj in context.selected_objects:
                sources.append({'source': obj, 'name': f"DummyAnim_{obj.name}"})
        elif context.mode == 'POSE':
            for bone in context.selected_pose_bones:
                armature = bone.id_data
                sources.append({'source': bone, 'name': f"DummyAnim_{armature.name}_{bone.name}"})
        return sources

    def create_dummies(self, context, sources):
        bpy.ops.object.select_all(action='DESELECT')
        dummies = []
        for src_info in sources:
            bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
            dummy = context.active_object
            dummy.name = src_info['name']
            
            for coll in dummy.users_collection:
                coll.objects.unlink(dummy)
            context.scene.collection.objects.link(dummy)
            dummies.append(dummy)
        return dummies

    def process_single_frame(self, context, pairs):
        for src_info, dummy in pairs:
            self.apply_transform(context, src_info['source'], dummy)

    def process_animation(self, context, pairs):
        props = context.scene.dummy_anim_creator_props
        for frame in range(props.frame_start, props.frame_end + 1):
            context.scene.frame_set(frame)
            for src_info, dummy in pairs:
                self.apply_transform(context, src_info['source'], dummy, bake=True, frame=frame)
    
    def apply_transform(self, context, source, dummy, bake=False, frame=0):
        props = context.scene.dummy_anim_creator_props
        if isinstance(source, bpy.types.Object):
            world_matrix = source.matrix_world
            source_for_rot_mode = source
        elif isinstance(source, bpy.types.PoseBone):
            armature = source.id_data
            world_matrix = armature.matrix_world @ source.matrix
            source_for_rot_mode = armature
        else:
            return

        loc, rot_quat, scale = world_matrix.decompose()

        if props.use_location:
            dummy.location = loc
            if bake: dummy.keyframe_insert(data_path="location", frame=frame)
        
        if props.use_scale:
            dummy.scale = scale
            if bake: dummy.keyframe_insert(data_path="scale", frame=frame)

        if props.use_rotation:
            target_rotation_mode = 'XYZ'
            if props.rotation_type == 'QUATERNION':
                target_rotation_mode = 'QUATERNION'
            elif props.rotation_type == 'CURRENT':
                target_rotation_mode = source_for_rot_mode.rotation_mode
            
            dummy.rotation_mode = target_rotation_mode
            
            if dummy.rotation_mode == 'QUATERNION':
                dummy.rotation_quaternion = rot_quat
                if bake: dummy.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            else:
                dummy.rotation_euler = rot_quat.to_euler(dummy.rotation_mode)
                if bake: dummy.keyframe_insert(data_path="rotation_euler", frame=frame)

# ------------------------------------------------------------------------
# UIパネル (サイドパネル)
# ------------------------------------------------------------------------

class VIEW3D_PT_DummyAnimPanel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tools"
    bl_label = "World Space Transform Baker"
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.dummy_anim_creator_props
        
        layout.label(text="Apply Transform")
        row = layout.row()
        row.prop(props, "use_location")
        row.prop(props, "use_rotation")
        row.prop(props, "use_scale")
        
        layout.separator()

        layout.label(text="Rotation Mode")
        layout.prop(props, "rotation_type", expand=True)
        
        layout.separator()
        
        layout.label(text="Bake Mode")
        layout.prop(props, "bake_mode", expand=True)

        box = layout.box()
        col = box.column()
        col.active = props.bake_mode == 'ANIMATION'
        
        col.label(text="Frame Range")
        row = col.row(align=True)
        row.prop(props, "frame_start", text="Start")
        row.prop(props, "frame_end", text="End")
        col.operator(WM_OT_GetSceneFrameRange.bl_idname, text="Get Scene Range")
        
        layout.separator()
        
        layout.operator(WM_OT_DummyAnimCreator.bl_idname, text="Bake Transform") # <- 修正2: ボタンの表示名

# ------------------------------------------------------------------------
# Blenderへの登録と登録解除
# ------------------------------------------------------------------------

classes = (
    DummyAnimCreatorProperties,
    WM_OT_GetSceneFrameRange,
    WM_OT_DummyAnimCreator,
    VIEW3D_PT_DummyAnimPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dummy_anim_creator_props = bpy.props.PointerProperty(type=DummyAnimCreatorProperties)

def unregister():
    if hasattr(bpy.types.Scene, 'dummy_anim_creator_props'):
        del bpy.types.Scene.dummy_anim_creator_props
    for cls in reversed(classes):
        if hasattr(bpy.utils, "unregister_class") and hasattr(bpy.types, cls.__name__):
            bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    try:
        unregister()
    except Exception as e:
        print(f"Failed to unregister cleanly: {e}")
    register()