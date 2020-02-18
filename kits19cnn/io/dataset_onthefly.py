import os
from os.path import join
from pathlib import Path
import numpy as np

import torch
from torch.utils.data import Dataset

from .preprocess import parse_slice_idx_to_str

class SliceDatasetOnTheFly(Dataset):
    """
    Reads from a directory of 2D slice numpy arrays and samples
    slices based on a specified sampling distribution. Assumes the data
    directory contains 2D slices processed by
    `io.Preprocessor.save_dir_as_2d()`.

    Samples slices on-the-fly.
    """
    def __init__(self, im_ids: np.array, in_dir: str, pos_slice_dict: dict,
                 transforms=None, preprocessing=None,
                 sampling_distribution=[0.33, 0.33, 0.34]):
        """
        Attributes
            im_ids (np.ndarray): of raw case folder names
            in_dir (str): path to where all of the case folders and slices
                are located
            pos_slice_dict (dict): dictionary generated by
                `io.Preprocessor.save_dir_as_2d()`.
                - goes by `slice_indices.json`
            transforms (albumentations.augmentation): transforms to apply
                before preprocessing. Defaults to HFlip and ToTensor
            preprocessing: ops to perform after transforms, such as
                z-score standardization. Defaults to None.
            sampling_distribution (List[float]): Class sampling distribution.
                This must add up to 1 and have a length equal to the number
                of classes.
        """
        print(f"Assuming inputs are .npy files...")
        self.im_ids = im_ids
        self.in_dir = in_dir
        self.pos_slice_dict = pos_slice_dict
        self.transforms = transforms
        self.preprocessing = preprocessing
        self.sampling_distribution = sampling_distribution
        assert np.sum(sampling_distribution) == 1, \
            "The sum of the sampling distribution probabilities should be 1."
        self.log_class_indices()
        print(f"Sampling classes from {self.classes}")

    def __getitem__(self, idx):
        # loads data as a numpy arr and then adds the channel + batch size dimensions
        case_id = self.im_ids[idx]
        x, y = self.load_slices(case_id)
        x, y = self.apply_transforms_and_preprocessing(x, y)
        # conversion to tensor if needed
        x = torch.from_numpy(x) if isinstance(x, np.ndarray) else x
        y = torch.from_numpy(y) if isinstance(y, np.ndarray) else y
        return (x.float(), y.long())

    def __len__(self):
        return len(self.im_ids)

    def apply_transforms_and_preprocessing(self, x, y):
        """
        Function name ^, if applicable.
        Input arrays must be in channels_last format for albumentations
        to work properly.
        This assumes you're using albumentations transforms.

        Args:
            x (np.ndarray): shape (h, w, n_channels)
            y (np.ndarray): shape (h, w, 1)
        Returns:
            transformed numpy arrays
        """
        if self.transforms:
            data_dict = self.transforms(image=x, mask=y)
            x, y = data_dict["image"], data_dict["mask"]

        if self.preprocessing:
            preprocessed = self.preprocessing(image=x, mask=y)
            x, y = preprocessed["image"], preprocessed["mask"]
        return (x, y)

    def load_slices(self, case_raw):
        """
        Gets the slice idx using self.get_slice_idx_str() and actually loads
        the appropriate slice array.

        Args:
            case_raw (str): each element of self.im_ids (case folder name)
        Returns:
            tuple of:
            - np.ndarray with shape (h, w, 1)
            - np.ndarray with shape (h, w, 1)
        """
        slice_idx_str, _ = self.get_slice_idx_str(case_raw)
        case_fpath = join(self.in_dir, case_raw)
        x_path = join(case_fpath, f"imaging_{slice_idx_str}.npy")
        y_path = join(case_fpath, f"segmentation_{slice_idx_str}.npy")
        return (np.load(x_path)[:, :, None], np.load(y_path)[:, :, None])

    def get_slice_idx_str(self, case_raw):
        """
        Gets the slice idx and processes it so that it fits how the arrays
        were saved by `io.Preprocessor.save_dir_as_2d`.
        Args:
            case_raw (str): each element of self.im_ids (case folder name)
        Returns:
            tuple of:
            - slice_idx_str: The parsed slice index
            - slice_idx (int): The raw slice index
        """
        slice_idx = self.get_slice_idx(case_raw)
        return (parse_slice_idx_to_str(slice_idx), slice_idx)

    def get_slice_idx(self, case_raw):
        """
        Gets a random slice index for a case for a sampled class from
        self.pos_slice_dict (that was generated by
        io.preprocess.Preprocessor.save_dir_as_2d()).

        Args:
            case_raw (str): each element of self.im_ids (case folder name)
        Returns:
            an integer representing a slice index
        """
        # finding random positive class index
        sampled_class = np.random.choice(self.classes,
                                         p=self.sampling_distribution)
        slice_indices = self.pos_slice_dict[case_raw][sampled_class]
        rand_idx = np.random.choice(slice_indices)
        return rand_idx

    def log_class_indices(self):
        """
        Fetches a list of classes indices from pos_slice_dict and assigns it
        to self.classes.
        """
        dummy_key = list(self.pos_slice_dict.keys())[0]
        dummy_value = self.pos_slice_dict[dummy_key]
        self.classes = list(dummy_value.keys())

class PseudoSliceDatasetOnTheFly(SliceDatasetOnTheFly):
    def __init__(self, im_ids: np.array, in_dir: str, pos_slice_dict: dict,
                 transforms=None, preprocessing=None,
                 sampling_distribution=[0.33, 0.33, 0.34],
                 num_pseudo_slices=5):
        """
        Reads from a directory of 2D slice numpy arrays and samples positive
        slices. Assumes the data directory contains 2D slices processed by
        `io.Preprocessor.save_dir_as_2d()`.
        Attributes
            im_ids (np.ndarray): of image names.
            in_dir (str): path to where all of the case folders and slices
                are located
            pos_slice_dict (dict): dictionary generated by
                `io.Preprocessor.save_dir_as_2d()`
                - goes by `slice_indices.json`
            transforms (albumentations.augmentation): transforms to apply
                before preprocessing. Defaults to HFlip and ToTensor
            preprocessing: ops to perform after transforms, such as
                z-score standardization. Defaults to None.
            sampling_distribution (List[float]): Class sampling distribution.
                This must add up to 1 and have a length equal to the number
                of classes.
            num_pseudo_slices (int): number of pseudo 3D slices. Defaults to 5.
                1 meaning no pseudo slices. If it's greater than 1, it must
                be odd (even numbers above and below)
        """
        super().__init__(im_ids=im_ids, in_dir=in_dir,
                         pos_slice_dict=pos_slice_dict, transforms=transforms,
                         preprocessing=preprocessing,
                         sampling_distribution=sampling_distribution)
        self.num_pseudo_slices = num_pseudo_slices
        assert num_pseudo_slices % 2 == 1, \
            "`num_pseudo_slices` must be odd. i.e. 7 -> 3 above and 3 below"

    def load_slices(self, case_raw):
        """
        Gets the slice idx using self.get_slice_idx_str() and actually loads
        the appropriate slice array. Returned arrays have shape:
            (h, w, num_pseudo_slices), (h, w, 1)
        for albumentations transforms.

        Args:
            case_raw (str): each element of self.im_ids (case folder name)
        Returns:
            tuple of:
            - np.ndarray with shape (h, w, num_pseudo_slices)
            - np.ndarray with shape (h, w, 1)
        """
        case_fpath = join(self.in_dir, case_raw)
        center_slice_idx_str, center_slice_idx = self.get_slice_idx_str(case_raw)
        min = center_slice_idx - (self.num_pseudo_slices - 1) // 2
        max = center_slice_idx + (self.num_pseudo_slices - 1) // 2 + 1

        x_path = join(case_fpath, f"imaging_{center_slice_idx_str}.npy")
        y_path = join(case_fpath, f"segmentation_{center_slice_idx_str}.npy")
        center_x, center_y = np.load(x_path)[:, :, None], np.load(y_path)[:, :, None]

        if self.num_pseudo_slices == 1:
            return (center_x, center_y)
        elif self.num_pseudo_slices > 1:
            # total shape: (h, w, num_pseudo_slices)
            x_arr = np.zeros(center_x.shape[:-1] + (self.num_pseudo_slices,))
            for idx, slice_idx in enumerate(range(min, max)):
                slice_idx_str = parse_slice_idx_to_str(slice_idx)
                x_path = join(case_fpath, f"imaging_{slice_idx_str}.npy")
                # loading slices if they exist
                if os.path.isfile(x_path):
                    x_arr[:, :, idx] = np.load(x_path)
            return (x_arr, center_y)
