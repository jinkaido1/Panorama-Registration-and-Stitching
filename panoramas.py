# Initial code for ex4.
# You may change this code, but keep the functions’ signatures
# You can also split the code to multiple files as long as this file’s API is unchanged

import shutil
from math import floor, ceil
import numpy as np
import os
import matplotlib.pyplot as plt
from scipy.ndimage.morphology import generate_binary_structure
from scipy.ndimage.filters import maximum_filter, convolve1d
from scipy.ndimage import label, center_of_mass, map_coordinates
from scipy.misc import imsave as imsave
import utils

DER = np.array([[1, 0, -1]])
K_FACTOR = 0.04
PYR_FACTOR = 0.25
SHAPE = 7


def harris_corner_detector(im):
    """
    Detects harris corners.
    Make sure the returned coordinates are x major!!!
    :param im: A 2D array representing an image.
    :return: An array with shape (N,2), where ret[i,:] are the [x,y] coordinates of the ith corner points.
    """
    ix = convolve1d(im, np.array([1, 0, -1]), )
    iy = np.transpose(convolve1d(im.T, np.array([1, 0, -1]), ))
    ixiy = utils.blur_spatial(ix * iy, 3)
    ix2 = utils.blur_spatial(ix ** 2, 3)
    iy2 = utils.blur_spatial(iy ** 2, 3)
    t = ix2 + iy2
    d = (ix2 * iy2) - (ixiy ** 2)
    R = d - K_FACTOR * (t ** 2)
    local_maxes = non_maximum_suppression(R)
    xy_coords = np.flip(np.argwhere(local_maxes == 1), 1)
    return xy_coords


def sample_descriptor(im, pos, desc_rad):
    """
    Samples descriptors at the given corners.
    :param im: A 2D array representing an image.
    :param pos: An array with shape (N,2), where pos[i,:] are the [x,y] coordinates of the ith corner point.
    :param desc_rad: "Radius" of descriptors to compute.
    :return: A 3D array with shape (N,K,K) containing the ith descriptor at desc[i,:,:].
    """
    x, y = pos.shape
    k = 1 + 2 * desc_rad
    desc = np.zeros((x, k, k))
    for i in range(x):
        a, b = np.meshgrid(np.arange(pos[i][0] - floor(k / 2), pos[i][0] + ceil(k / 2), 1),
                           np.arange(pos[i][1] - floor(k / 2), pos[i][1] + ceil(k / 2), 1))
        cords = np.stack([b, a]).reshape(2, k ** 2)
        res = map_coordinates(im, cords, order=1, prefilter=False).reshape((k, k))
        norm = np.linalg.norm(res - np.mean(res))
        if norm == 0:
            desc[i] = (res - np.mean(res))
        else:
            res = (res - np.mean(res)) / norm
        desc[i] = res
    return desc


def find_features(pyr):
    """
    Detects and extracts feature points from a pyramid.
    :param pyr: Gaussian pyramid of a grayscale image having 3 levels.
    :return: A list containing:
    1) An array with shape (N,2) of [x,y] feature location per row found in the image.
    These coordinates are provided at the pyramid level pyr[0].
    2) A feature descriptor array with shape (N,K,K)
    """
    corners = spread_out_corners(pyr[0], SHAPE, SHAPE, 3)
    descriptor = sample_descriptor(pyr[2], PYR_FACTOR * corners, 3)
    return corners, descriptor


def match_features(desc1, desc2, min_score):
    """
    Return indices of matching descriptors.
    :param desc1: A feature descriptor array with shape (N1,K,K).
    :param desc2: A feature descriptor array with shape (N2,K,K).
    :param min_score: Minimal match score.
    :return: A list containing:
    1) An array with shape (M,) and dtype int of matching indices in desc1.
    2) An array with shape (M,) and dtype int of matching indices in desc2.
    """
    j = desc1.shape[0]
    t = desc1.shape[1] ** 2
    k = desc2.shape[0]
    scoremat = np.dot(desc1.reshape((j, t)), desc2.reshape((k, t)).T)
    boolmat1 = np.zeros(scoremat.shape).astype(np.bool)
    boolmat2 = np.zeros(scoremat.shape).astype(np.bool)
    scoremat2 = scoremat.copy()
    for i in range(2):
        i, j = np.where((scoremat2.T == np.amax(scoremat2, axis=1)))
        boolmat1[j, i] = True
        scoremat2[j, i] = 0
    scoremat2 = scoremat.copy()
    for i in range(2):
        i, j = np.where(scoremat2 == np.amax(scoremat2, axis=0))
        boolmat2[i, j] = True
        scoremat2[i, j] = 0
    i, j = np.where((boolmat1 & boolmat2) & (scoremat > min_score))
    return i, j


def apply_homography(pos1, H12):
    """
    Apply homography to inhomogenous points.
    :param pos1: An array with shape (N,2) of [x,y] point coordinates.
    :param H12: A 3x3 homography matrix.
    :return: An array with the same shape as pos1 with [x,y] point coordinates obtained from transforming pos1 using H12.
    """

    res = np.vstack([pos1.T, np.ones((pos1.shape[0],))])
    res = H12 @ res
    return (res / res[2, :])[0:2, :].T


def ransac_homography(points1, points2, num_iter, inlier_tol, translation_only=False):
    """
    Computes homography between two sets of points using RANSAC.
    :param pos1: An array with shape (N,2) containing N rows of [x,y] coordinates of matched points in image 1.
    :param pos2: An array with shape (N,2) containing N rows of [x,y] coordinates of matched points in image 2.
    :param num_iter: Number of RANSAC iterations to perform.
    :param inlier_tol: inlier tolerance threshold.
    :return: A list containing:
    1) A 3x3 normalized homography matrix.
    2) An Array with shape (S,) where S is the number of inliers,
    containing the indices in pos1/pos2 of the maximal set of inlier matches found.
    """

    num_of_points = 4
    bestinliers = np.zeros((0, 0))
    for i in range(num_iter):
        random = np.random.randint(0, points1.shape[0], (num_of_points,)).astype(np.int32)
        p1 = points1[random]
        p2 = points2[random]
        hom = estimate_rigid_transform(p1, p2, translation_only)
        p2t = apply_homography(points1, hom)
        E = np.linalg.norm((points2 - p2t), axis=1)
        inliersidx = np.where((E < inlier_tol))[0]
        if inliersidx.size > bestinliers.size:
            bestinliers = inliersidx
    H = estimate_rigid_transform(points1[bestinliers], points2[bestinliers])
    return H, bestinliers


def display_matches(im1, im2, points1, points2, inliers):
    """
    Dispalay matching points.
    :param im1: A grayscale image.
    :param im2: A grayscale image.
    :parma pos1: An aray shape (N,2), containing N rows of [x,y] coordinates of matched points in im1.
    :param pos2: An aray shape (N,2), containing N rows of [x,y] coordinates of matched points in im2.
    :param inliers: An array with shape (S,) of inlier matches.
    """
    im = np.hstack([im1, im2])
    points2[:, 0] += im1.shape[1]
    plt.imshow(im, cmap="gray")
    for i in range(points1.shape[0]):
        if i not in inliers:
            plt.plot((points1[i, 0], points2[i, 0]), (points1[i, 1], points2[i, 1]), mfc='r', c='b', lw=.2, ms=2,
                     marker='o')
    for i in inliers:
        plt.plot((points1[i, 0], points2[i, 0]), (points1[i, 1], points2[i, 1]), mfc='r', c='y', lw=1, ms=2,
                 marker='o')
    plt.show()


def accumulate_homographies(H_succesive, m):
    """
    Convert a list of succesive homographies to a
    list of homographies to a common reference frame.
    :param H_successive: A list of M-1 3x3 homography
    matrices where H_successive[i] is a homography which transforms points
    from coordinate system i to coordinate system i+1.
    :param m: Index of the coordinate system towards which we would like to
    accumulate the given homographies.
    :return: A list of M 3x3 homography matrices,
    where H2m[i] transforms points from coordinate system i to coordinate system m
    """
    H_hat = [[]] * (len(H_succesive) + 1)
    H_hat[m] = np.eye(3)
    for i in range(m - 1, -1, -1):
        H_hat[i] = np.dot(H_hat[i + 1], H_succesive[i])
    for i in range(m + 1, len(H_succesive) + 1):
        H_hat[i] = np.dot(H_hat[i - 1], np.linalg.inv(H_succesive[i - 1]))
    return H_hat


def warp_channel(image, homography):
    """
    Warps a 2D image with a given homography.
    :param image: a 2D image.
    :param homography: homograhpy.
    :return: A 2d warped image.
    """
    bounding = compute_bounding_box(homography, image.shape[1], image.shape[0])
    range_x = np.arange(bounding[0, 0], bounding[1, 0])
    range_y = np.arange(bounding[0, 1], bounding[1, 1])
    new_grid = np.meshgrid(range_x, range_y)

    x ,y = new_grid[0].shape[0],new_grid[1].shape[1]

    range_x = (new_grid[0]).flatten()
    range_y = new_grid[1].flatten()
    grid = np.vstack((range_x, range_y)).T
    coords_original = apply_homography(grid, np.linalg.inv(homography))

    warped = map_coordinates(image, np.transpose(np.flip(coords_original, axis=1)), order=1,
                             prefilter=False).reshape(new_grid[0].shape[0], new_grid[1].shape[1])
    return warped


def warp_image(image, homography):
    """
    Warps an RGB image with a given homography.
    :param image: an RGB image.
    :param homography: homograhpy.
    :return: A warped image.
    """
    return np.dstack([warp_channel(image[..., channel], homography) for channel in range(3)])


def compute_bounding_box(homography, w, h):
    """
    computes bounding box of warped image under homography, without actually warping the image
    :param homography: homography
    :param w: width of the image
    :param h: height of the image
    :return: 2x2 array, where the first row is [x,y] of the top left corner,
    and the second row is the [x,y] of the bottom right corner
    """
    points = np.array([[0, 0], [0, h - 1], [w - 1, 0], [w - 1, h - 1]])
    tpoints = apply_homography(points, homography)
    top_l_x = np.floor(np.min(tpoints[:, 0])).astype(int)
    top_l_y = np.floor(np.min(tpoints[:, 1])).astype(int)
    bottom_r_x = np.ceil(np.max(tpoints[:, 0])).astype(int)
    bottom_r_y = np.ceil(np.max(tpoints[:, 1])).astype(int)
    return np.array([[top_l_x, top_l_y], [bottom_r_x, bottom_r_y]])


def filter_homographies_with_translation(homographies, minimum_right_translation):
    """
    Filters rigid transformations encoded as homographies by the amount of translation from left to right.
    :param homographies: homograhpies to filter.
    :param minimum_right_translation: amount of translation below which the transformation is discarded.
    :return: filtered homographies..
    """

    translation_over_thresh = [0]
    last = homographies[0][0, -1]
    for i in range(1, len(homographies)):
        if homographies[i][0, -1] - last > minimum_right_translation:
            translation_over_thresh.append(i)
            last = homographies[i][0, -1]
    return np.array(translation_over_thresh).astype(np.int)


def estimate_rigid_transform(points1, points2, translation_only=False):
    """
    Computes rigid transforming points1 towards points2, using least squares method.
    points1[i,:] corresponds to poins2[i,:]. In every point, the first coordinate is *x*.
    :param points1: array with shape (N,2). Holds coordinates of corresponding points from image 1.
    :param points2: array with shape (N,2). Holds coordinates of corresponding points from image 2.
    :param translation_only: whether to compute translation only. False (default) to compute rotation as well.
    :return: A 3x3 array with the computed homography.
    """

    centroid1 = points1.mean(axis=0)
    centroid2 = points2.mean(axis=0)

    if translation_only:
        rotation = np.eye(2)
        translation = centroid2 - centroid1

    else:
        centered_points1 = points1 - centroid1
        centered_points2 = points2 - centroid2

        sigma = np.dot(centered_points2.T, centered_points1)
        U, _, Vt = np.linalg.svd(sigma)

        rotation = np.dot(U, Vt)
        translation = np.dot(-rotation, centroid1) + centroid2

    H = np.eye(3)
    H[:2, :2] = rotation
    H[:2, 2] = translation
    return H


def least_squares_homography(points1, points2):
    """
    Computes homography transforming points1 towards points2, using least squares method.
    points1[i,:] corresponds to poins2[i,:]. In every point, the first coordinate is *x*.
    :param points1: array with shape (N,2). Holds coordinates of corresponding points from image 1.
    :param points2: array with shape (N,2). Holds coordinates of corresponding points from image 2.
    :return: A 3X3 array with the computed homography. In case of instable solutions returns None.
    """

    p1, p2 = points1, points2
    o0, o1 = np.zeros((p1.shape[0], 1)), np.ones((p1.shape[0], 1))
    A = np.vstack(
        [np.hstack([p1[:, :1], o0, -p1[:, :1] * p2[:, :1], p1[:, 1:], o0, -p1[:, 1:] * p2[:, :1], o1, o0]),
         np.hstack([o0, p1[:, :1], -p1[:, :1] * p2[:, 1:], o0, p1[:, 1:], -p1[:, 1:] * p2[:, 1:], o0, o1])])
    # Return None for unstable solutions
    if np.linalg.matrix_rank(A, 1e-3) < 8:
        return None
    if A.shape[0] == 8 and np.linalg.cond(A) > 1e10:
        return None

    H = np.linalg.lstsq(A, p2.T.flatten())[0]
    H = np.r_[H, 1]
    return H.reshape((3, 3)).T


def non_maximum_suppression(image):
    """
    Finds local maximas of an image.
    :param image: A 2D array representing an image.
    :return: A boolean array with the same shape as the input image, where True indicates local maximum.
    """

    # Find local maximas.
    neighborhood = generate_binary_structure(2, 2)
    local_max = maximum_filter(image, footprint=neighborhood) == image
    local_max[image < (image.max() * 0.1)] = False

    # Erode areas to single points.
    lbs, num = label(local_max)
    centers = center_of_mass(local_max, lbs, np.arange(num) + 1)
    centers = np.stack(centers).round().astype(np.int)
    ret = np.zeros_like(image, dtype=np.bool)
    ret[centers[:, 0], centers[:, 1]] = True

    return ret


def spread_out_corners(im, m, n, radius):
    """
    Splits the image im to m by n rectangles and uses harris_corner_detector on each.
    :param im: A 2D array representing an image.
    :param m: Vertical number of rectangles.
    :param n: Horizontal number of rectangles.
    :param radius: Minimal distance of corner points from the boundary of the image.
    :return: An array with shape (N,2), where ret[i,:] are the [x,y] coordinates of the ith corner points.
    """

    corners = [np.empty((0, 2), dtype=np.int)]
    x_bound = np.linspace(0, im.shape[1], n + 1, dtype=np.int)
    y_bound = np.linspace(0, im.shape[0], m + 1, dtype=np.int)
    for i in range(n):
        for j in range(m):
            # Use Harris detector on every sub image.
            sub_im = im[y_bound[j]:y_bound[j + 1], x_bound[i]:x_bound[i + 1]]
            sub_corners = harris_corner_detector(sub_im)
            sub_corners += np.array([x_bound[i], y_bound[j]])[np.newaxis, :]
            corners.append(sub_corners)
    corners = np.vstack(corners)
    legit = ((corners[:, 0] > radius) & (corners[:, 0] < im.shape[1] - radius) &
             (corners[:, 1] > radius) & (corners[:, 1] < im.shape[0] - radius))
    ret = corners[legit, :]
    return ret


class PanoramicVideoGenerator:
    """
    Generates panorama from a set of images.
    """

    def __init__(self, data_dir, file_prefix, num_images):
        """
        The naming convention for a sequence of images is file_prefixN.jpg,
        where N is a running number 001, 002, 003...
        :param data_dir: path to input images.
        :param file_prefix: see above.
        :param num_images: number of images to produce the panoramas with.
        """
        self.file_prefix = file_prefix
        self.files = [os.path.join(data_dir, '%s%03d.jpg' % (file_prefix, i + 1)) for i in range(num_images)]
        self.files = list(filter(os.path.exists, self.files))
        self.panoramas = None
        self.homographies = None
        print('found %d images' % len(self.files))

    def align_images(self, translation_only=False):
        """
        compute homographies between all images to a common coordinate system
        :param translation_only: see estimte_rigid_transform
        """
        # Extract feature point locations and descriptors.
        points_and_descriptors = []
        for file in self.files:
            image = utils.read_image(file, 1)
            self.h, self.w = image.shape
            pyramid, _ = utils.build_gaussian_pyramid(image, 3, 7)
            points_and_descriptors.append(find_features(pyramid))

        # Compute homographies between successive pairs of images.
        Hs = []
        for i in range(len(points_and_descriptors) - 1):
            points1, points2 = points_and_descriptors[i][0], points_and_descriptors[i + 1][0]
            desc1, desc2 = points_and_descriptors[i][1], points_and_descriptors[i + 1][1]

            # Find matching feature points.
            ind1, ind2 = match_features(desc1, desc2, .7)
            points1, points2 = points1[ind1, :], points2[ind2, :]

            # Compute homography using RANSAC.
            H12, inliers = ransac_homography(points1, points2, 100, 6, translation_only)

            # Uncomment for debugging: display inliers and outliers among matching points.
            # In the submitted code this function should be commented out!
            # display_matches(self.images[i], self.images[i+1], points1 , points2, inliers)

            Hs.append(H12)

        # Compute composite homographies from the central coordinate system.
        accumulated_homographies = accumulate_homographies(Hs, (len(Hs) - 1) // 2)
        self.homographies = np.stack(accumulated_homographies)
        self.frames_for_panoramas = filter_homographies_with_translation(self.homographies,
                                                                         minimum_right_translation=5)
        self.homographies = self.homographies[self.frames_for_panoramas]

    def generate_panoramic_images(self, number_of_panoramas):
        """
        combine slices from input images to panoramas.
        :param number_of_panoramas: how many different slices to take from each input image
        """
        assert self.homographies is not None

        # compute bounding boxes of all warped input images in the coordinate system of the middle image (as given by the homographies)
        self.bounding_boxes = np.zeros((self.frames_for_panoramas.size, 2, 2))
        for i in range(self.frames_for_panoramas.size):
            self.bounding_boxes[i] = compute_bounding_box(self.homographies[i], self.w, self.h)

        # change our reference coordinate system to the panoramas
        # all panoramas share the same coordinate system
        global_offset = np.min(self.bounding_boxes, axis=(0, 1))
        self.bounding_boxes -= global_offset

        slice_centers = np.linspace(0, self.w, number_of_panoramas + 2, endpoint=True, dtype=np.int)[1:-1]
        warped_slice_centers = np.zeros((number_of_panoramas, self.frames_for_panoramas.size))
        # every slice is a different panorama, it indicates the slices of the input images from which the panorama
        # will be concatenated
        for i in range(slice_centers.size):
            slice_center_2d = np.array([slice_centers[i], self.h // 2])[None, :]
            # homography warps the slice center to the coordinate system of the middle image
            warped_centers = [apply_homography(slice_center_2d, h) for h in self.homographies]
            # we are actually only interested in the x coordinate of each slice center in the panoramas' coordinate system
            warped_slice_centers[i] = np.array(warped_centers)[:, :, 0].squeeze() - global_offset[0]

        panorama_size = np.max(self.bounding_boxes, axis=(0, 1)).astype(np.int) + 1

        # boundary between input images in the panorama
        x_strip_boundary = ((warped_slice_centers[:, :-1] + warped_slice_centers[:, 1:]) / 2)
        x_strip_boundary = np.hstack([np.zeros((number_of_panoramas, 1)),
                                      x_strip_boundary,
                                      np.ones((number_of_panoramas, 1)) * panorama_size[0]])
        x_strip_boundary = x_strip_boundary.round().astype(np.int)

        self.panoramas = np.zeros((number_of_panoramas, panorama_size[1], panorama_size[0], 3), dtype=np.float64)
        for i, frame_index in enumerate(self.frames_for_panoramas):
            # warp every input image once, and populate all panoramas
            image = utils.read_image(self.files[frame_index], 2)
            warped_image = warp_image(image, self.homographies[i])
            x_offset, y_offset = self.bounding_boxes[i][0].astype(np.int)
            y_bottom = y_offset + warped_image.shape[0]

            for panorama_index in range(number_of_panoramas):
                # take strip of warped image and paste to current panorama
                boundaries = x_strip_boundary[panorama_index, i:i + 2]
                image_strip = warped_image[:, boundaries[0] - x_offset: boundaries[1] - x_offset]
                x_end = boundaries[0] + image_strip.shape[1]
                self.panoramas[panorama_index, y_offset:y_bottom, boundaries[0]:x_end] = image_strip

        # crop out areas not recorded from enough angles
        # assert will fail if there is overlap in field of view between the left most image and the right most image
        crop_left = int(self.bounding_boxes[0][1, 0])
        crop_right = int(self.bounding_boxes[-1][0, 0])
        assert crop_left < crop_right, 'for testing your code with a few images do not crop.'
        print(crop_left, crop_right)
        self.panoramas = self.panoramas[:, :, crop_left:crop_right, :]

    def save_panoramas_to_video(self):
        assert self.panoramas is not None
        out_folder = 'tmp_folder_for_panoramic_frames/%s' % self.file_prefix
        try:
            shutil.rmtree(out_folder)
        except:
            print('could not remove folder')
            pass
        os.makedirs(out_folder)
        # save individual panorama images to 'tmp_folder_for_panoramic_frames'
        for i, panorama in enumerate(self.panoramas):
            imsave('%s/panorama%02d.png' % (out_folder, i + 1), panorama)
        if os.path.exists('%s.mp4' % self.file_prefix):
            os.remove('%s.mp4' % self.file_prefix)
        # write output video to current folder
        os.system('ffmpeg -framerate 3 -i %s/panorama%%02d.png %s.mp4' %
                  (out_folder, self.file_prefix))

    def show_panorama(self, panorama_index, figsize=(20, 20)):
        assert self.panoramas is not None
        plt.figure(figsize=figsize)
        plt.imshow(self.panoramas[panorama_index].clip(0, 1))
        plt.show()



