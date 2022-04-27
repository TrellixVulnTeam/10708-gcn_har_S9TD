num_person = 3
model = dict(
    type='SkeletonGCN',
    backbone=dict(
        type='LOCGCN',
        in_channels=3,
        edge_importance_weighting=True,
        graph_cfg=dict(layout='coco', strategy='spatial')),
    cls_head=dict(
        type='STGCNHead',
        num_classes=60,
        in_channels=256,
        num_person=3,
        spatial_type='avg',
        loss_cls=dict(type='CrossEntropyLoss')),
    train_cfg=None,
    test_cfg=None)
dataset_type = 'PoseDataset'
ann_file_train = '/home/tong/10708/skeleton/skeleton_train/'
ann_file_val = '/home/tong/10708/skeleton/skeleton_val/'
train_pipeline = [
    dict(type='PaddingWithLoop', clip_len=30),
    dict(type='PoseDecode'),
    dict(
        type='FormatGCNInput',
        num_person=3,
        input_format='NCTVM',
        use_node_feature=True),
    dict(type='PoseNormalize'),
    dict(type='Collect', keys=['keypoint', 'label'], meta_keys=[]),
    dict(type='ToTensor', keys=['keypoint'])
]
val_pipeline = [
    dict(type='PaddingWithLoop', clip_len=30),
    dict(type='PoseDecode'),
    dict(
        type='FormatGCNInput',
        num_person=3,
        input_format='NCTVM',
        use_node_feature=True),
    dict(type='PoseNormalize'),
    dict(type='Collect', keys=['keypoint', 'label'], meta_keys=[]),
    dict(type='ToTensor', keys=['keypoint'])
]
test_pipeline = [
    dict(type='PaddingWithLoop', clip_len=30),
    dict(type='PoseDecode'),
    dict(
        type='FormatGCNInput',
        num_person=3,
        input_format='NCTVM',
        use_node_feature=True),
    dict(type='PoseNormalize'),
    dict(type='Collect', keys=['keypoint', 'label'], meta_keys=[]),
    dict(type='ToTensor', keys=['keypoint'])
]
data = dict(
    videos_per_gpu=48,
    workers_per_gpu=4,
    val_dataloader=dict(shuffle=False),
    test_dataloader=dict(videos_per_gpu=4),
    train=dict(
        type='PoseDataset',
        ann_file='/home/tong/10708/skeleton/skeleton_train/',
        data_prefix='',
        pipeline=[
            dict(type='PaddingWithLoop', clip_len=30),
            dict(type='PoseDecode'),
            dict(
                type='FormatGCNInput',
                num_person=3,
                input_format='NCTVM',
                use_node_feature=True),
            dict(type='PoseNormalize'),
            dict(type='Collect', keys=['keypoint', 'label'], meta_keys=[]),
            dict(type='ToTensor', keys=['keypoint'])
        ]),
    val=dict(
        type='PoseDataset',
        ann_file='/home/tong/10708/skeleton/skeleton_val/',
        data_prefix='',
        pipeline=[
            dict(type='PaddingWithLoop', clip_len=30),
            dict(type='PoseDecode'),
            dict(
                type='FormatGCNInput',
                num_person=3,
                input_format='NCTVM',
                use_node_feature=True),
            dict(type='PoseNormalize'),
            dict(type='Collect', keys=['keypoint', 'label'], meta_keys=[]),
            dict(type='ToTensor', keys=['keypoint'])
        ]),
    test=dict(
        type='PoseDataset',
        ann_file='/home/tong/10708/skeleton/skeleton_val/',
        data_prefix='',
        pipeline=[
            dict(type='PaddingWithLoop', clip_len=30),
            dict(type='PoseDecode'),
            dict(
                type='FormatGCNInput',
                num_person=3,
                input_format='NCTVM',
                use_node_feature=True),
            dict(type='PoseNormalize'),
            dict(type='Collect', keys=['keypoint', 'label'], meta_keys=[]),
            dict(type='ToTensor', keys=['keypoint'])
        ]))
optimizer = dict(type='Adam', lr=0.0005)
optimizer_config = dict(grad_clip=None)
lr_config = dict(policy='step', step=[10, 40, 70])
total_epochs = 80
checkpoint_config = dict(interval=5)
evaluation = dict(interval=2, metrics=['top_k_accuracy'])
log_config = dict(interval=10, hooks=[dict(type='TextLoggerHook')])
dist_params = dict(backend='nccl')
log_level = 'INFO'
work_dir = './stgcn_loc_3_modify_dataset/'
load_from = None
resume_from = None
workflow = [('train', 1)]
gpu_ids = range(0, 4)
omnisource = False
module_hooks = []