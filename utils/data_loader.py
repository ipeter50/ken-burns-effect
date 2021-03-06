import os

import cv2
import h5py
import imageio as io
import torch
import torchvision.transforms as transforms
from PIL import Image
from torch.utils.data import Dataset

from utils.utils import *


class Dataset(Dataset):
    def __init__(self, datasets, max_dim=1024, mode='disparity', imagenet_path=None):
        self.datasets = datasets

        self.data_path = []
        self.data_params = []
        for dataset in self.datasets:
            print(dataset)
            self.data_path.append(dataset['path'])
            self.data_params.append(dataset['params'])

        self.max_dim = max_dim
        self.max_h = 756
        self.max_w = 1024

        self.output_depth = False
        self.cropping = True

        self.mode = mode
        
        self.image_preparation = transforms.Compose([transforms.ToTensor(),
                                               transforms.Normalize((.5, .5, .5), (.5, .5, .5))])

        self.mask_preparation = transforms.Compose([transforms.RandomAffine(90, (0.05, 0.15), (1, 1.2)),
                                            transforms.RandomResizedCrop((756, 1024), scale=(0.8, 1)),
                                            transforms.ToTensor()])

        self.depth_preparation = transforms.Compose([transforms.ToTensor()])
        
        self.disparity_preparation = transforms.Compose([transforms.ToTensor()])
        
        
        self.images_paths = []
        self.depth_paths = []
        self.disparity_paths = []
        
        if type(self.data_path) is list:
            for id_dataset, path in enumerate(self.data_path):
                for img in os.listdir(path + 'images/'):
                    if self.datasets[id_dataset]['name'] == 'mega':
                        self.images_paths.append((path + 'images/' + img, id_dataset)) 
                        self.depth_paths.append((path + 'depth/' + img[:-3] + 'h5', id_dataset))
                    elif self.datasets[id_dataset]['name'] == 'gta':
                        self.images_paths.append((path + 'images/' + img, id_dataset)) 
                        self.depth_paths.append((path + 'depths/' + img[:-3] + 'exr', id_dataset))
                    else:
                        self.images_paths.append((path + 'images/' + img, id_dataset)) 
                        self.depth_paths.append((path + 'depth/' + img, id_dataset))
                    # self.disparity_paths.append(path + 'disparity/' + img)
        else:
            print('Please pass dataset path as list')
        
        ######################
        # Get imagenet paths #
        ######################
        
        if imagenet_path is not None:
            image_net_folder = imagenet_path
        else:
            image_net_folder = '/scratch/s182169/ImageNet/ILSVRC/Data/DET/train/'

        self.paths = os.listdir(image_net_folder)
        
        self.imagenet_preparation = transforms.Compose([
                                                transforms.RandomResizedCrop(256),
                                                transforms.ToTensor(),
                                                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])])

        self.imagenet_paths = []

        for sub_dir_path in self.paths:
            for img in os.listdir(os.path.join(image_net_folder, sub_dir_path)):
                self.imagenet_paths.append(os.path.join(image_net_folder, sub_dir_path, img))
        
        self.imagenet_len = len(self.imagenet_paths)        


    def __getitem__(self, index):
        path_img, id_dataset = self.images_paths[index]
        path_depth = self.depth_paths[index][0]

        
        numpyImage = cv2.imread(filename=path_img, flags=cv2.IMREAD_COLOR)
        numpyImage = cv2.cvtColor(numpyImage, cv2.COLOR_BGR2RGB) # convert image into RGB (cv2 loads by default in BGR)

        if self.datasets[id_dataset]['name'] == 'mega':
            hdf5_file_read = h5py.File(path_depth,'r')
            gt_depth = hdf5_file_read.get('/depth')
            numpyDepth = np.array(gt_depth)
            hdf5_file_read.close()

            numpyMasks = (numpyDepth != 0).astype(np.float)
            numpyDepth[numpyMasks == 0] = np.inf
            numpyDisparity = self.data_params[id_dataset]['focal'] * self.data_params[id_dataset]['baseline'] / (numpyDepth + 1e-4)
        else:
            numpyDepth = cv2.imread(filename=path_depth, flags=-1) # -1 flag allows to keep 32 bits values for depth
            if self.datasets[id_dataset]['name'] == 'gta':
                numpyDepth[numpyDepth == np.inf] = self.data_params[id_dataset]['focal'] * self.data_params[id_dataset]['baseline']

            numpyMasks = np.ones(numpyDepth.shape)
            numpyDisparity = self.data_params[id_dataset]['focal'] * self.data_params[id_dataset]['baseline'] / (numpyDepth + 1e-4)
            

        if self.cropping:
            start_h = np.random.randint(0, numpyImage.shape[0] - self.max_h + 1)
            start_w = np.random.randint(0, numpyImage.shape[1] - self.max_w + 1)

            numpyDepth = numpyDepth[start_h:start_h + self.max_h, start_w:start_w + self.max_w]
            numpyDisparity = numpyDisparity[start_h:start_h + self.max_h, start_w:start_w + self.max_w]
            numpyImage = numpyImage[start_h:start_h + self.max_h, start_w:start_w + self.max_w]
            numpyMasks = numpyMasks[start_h:start_h + self.max_h, start_w:start_w + self.max_w]                          


        # resize image to 1024 pixels max, conserving aspect ratio
        intWidth = numpyImage.shape[1]
        intHeight = numpyImage.shape[0]

        dblRatio = float(intWidth) / float(intHeight)

        intWidth = min(int(self.max_dim * dblRatio), self.max_dim)
        intHeight = min(int(self.max_dim / dblRatio), self.max_dim)


        # resize images according to training mode, helps to reduce memory footprint
        if self.mode == 'disparity':
            ratios = {'image': 2, 'disparity': 4, 'masks': 4}
        elif self.mode == 'refine' or self.mode == 'eval' or self.mode == 'inpaint-eval':
            ratios = {'image': 1, 'disparity':1, 'masks':1} 
        elif self.mode == 'inpainting':
            ratios = {'image': 2, 'disparity':2, 'masks':2} 

        intWidthImg, intHeightImg, maxDimImg = int(intWidth/ratios['image']), int(intHeight/ratios['image']), int(self.max_dim / ratios['image'])
        intWidthDisp, intHeightDisp, maxDimDisp = int(intWidth/ratios['disparity']), int(intHeight/ratios['disparity']), int(self.max_dim / ratios['disparity'])
        intWidthMasks, intHeightMasks, maxDimMasks = int(intWidth/ratios['masks']), int(intHeight/ratios['masks']), int(self.max_dim / ratios['masks'])

      
        numpyImage = cv2.resize(src=numpyImage, dsize=(intWidthImg, intHeightImg), fx=0.0, fy=0.0, interpolation=cv2.INTER_AREA)
        numpyDepth = cv2.resize(src=numpyDepth, dsize=(intWidthDisp, intHeightDisp), fx=0.0, fy=0.0, interpolation=cv2.INTER_AREA)
        numpyDisparity = cv2.resize(src=numpyDisparity, dsize=(intWidthDisp, intHeightDisp), fx=0.0, fy=0.0, interpolation=cv2.INTER_AREA)
        numpyMasks = cv2.resize(src=numpyMasks, dsize=(intWidthMasks, intHeightMasks), fx=0.0, fy=0.0, interpolation=cv2.INTER_AREA).clip(0,1)
            

        # normalize and convert into torch Tensors
        self.image = self.image_preparation(numpyImage)#.to(device)
        self.depth = self.depth_preparation(numpyDepth.astype('float32'))#.to(device)
        self.disparity = self.disparity_preparation(numpyDisparity.astype('float32'))#.to(device)
        self.masks = self.disparity_preparation(numpyMasks.astype('float32'))#.to(device)

        ######################
        # get imagenet image #
        ######################

        # path_img = self.imagenet_paths[index%self.imagenet_len]
        path_img = self.imagenet_paths[np.random.randint(self.imagenet_len)]
        
        numpyImageNet = cv2.imread(filename=path_img, flags=cv2.IMREAD_COLOR)
        numpyImageNet = cv2.cvtColor(numpyImageNet, cv2.COLOR_BGR2RGB)

        PILImage = Image.fromarray(numpyImageNet)
        self.imageNet = self.imagenet_preparation(PILImage)#.to(device)

        
        if self.mode == 'inpainting' or self.mode == 'inpaint-eval':
            self.zoom_from, self.zoom_to = get_random_zoom(*self.depth.shape[-2:])


        if self.output_depth:
            return None
        elif self.mode == 'inpainting' or self.mode == 'inpaint-eval':
            return (self.image, self.disparity, self.depth, self.zoom_from, self.zoom_to, id_dataset)
        else:
            return (self.image, self.disparity, self.masks, self.imageNet, id_dataset)

    def __len__(self):
        return len(self.images_paths)
    
    def pin_memory(self):
        self.image = self.image.pin_memory()
        self.depth = self.depth.pin_memory()
        self.disparity = self.disparity.pin_memory()
        self.masks = self.masks.pin_memory()
        # self.id_dataset = self.id_dataset.pin_memory()
        return self


    def get_dataloader(self, batch_size=4, shuffle=True):
        data_loader = torch.utils.data.DataLoader(self, batch_size=batch_size, shuffle=shuffle, pin_memory=True, num_workers=2)
        return data_loader

