from datetime import datetime
from pathlib import Path
from typing import Union

import itk
import numpy as np

from medio.metadata.affine import Affine
from medio.metadata.dcm_uid import generate_uid
from medio.metadata.itk_orientation import itk_orientation_code
from medio.metadata.metadata import MetaData, check_dcm_ornt
from medio.utils.files import is_dicom, make_dir
from medio.utils.files import parse_series_uids


class ItkIO:
    coord_sys = "itk"
    DEFAULT_COMPONENTS_AXIS = 0  # in the transposed image
    # default image type:
    dimension = 3
    pixel_type = itk.ctype("short")  # signed short - int16
    image_type = itk.Image[pixel_type, dimension]

    @staticmethod
    def read_img(
        input_path,
        desired_axcodes=None,
        header=False,
        components_axis=None,
        pixel_type=pixel_type,
        fallback_only=True,
        series=None,
        private_tags=False,
    ):
        """
        The main reader function, reads images and performs reorientation and unpacking
        :param input_path: path of image file or directory containing dicom series
        :param desired_axcodes: string or tuple - e.g. 'LPI', ('R', 'A', 'S')
        :param header: whether to include a header attribute with additional metadata in the returned metadata
        :param components_axis: if not None and the image is channeled (e.g. RGB) move the channels to channels_axis
        :param pixel_type: preferred itk pixel type for the image
        :param fallback_only: if True, finds the pixel_type automatically and uses pixel_type only if failed
        :param series: str or int of the series to read (in the case of multiple series in a directory)
        :return: numpy image and metadata object which includes pixdim, affine, original orientation string and
        coordinates system
        """
        if header:
            # Currently, only DICOM will use imageio (GDCM). For NIfTI, we'll use ITK default reader.
            imageio = itk.GDCMImageIO.New()
            if private_tags:
                imageio.LoadPrivateTagsOn()
        else:
            imageio = None
        input_path = Path(input_path)
        if input_path.is_dir():
            # We assume that the directory contains dicom series, do imageio will work, if used.
            if imageio is not None:
                # we need to set the imageio to the reader, but with fallback_only=True it will not set it unless it fails
                fallback_only = False
            img = ItkIO.read_dir(
                str(input_path), pixel_type, fallback_only, series, imageio
            )
        elif input_path.is_file():
            # If the input file is not a dicom (e.g. NIfTI), fallback to not use imageio.
            use_dicom_imageio = imageio.CanReadFile(str(input_path))
            if use_dicom_imageio:
                # we need to set the imageio to the reader, but with fallback_only=True it will not set it unless it fails
                fallback_only = False
            else:
                imageio = None
            img = ItkIO.read_img_file(
                str(input_path), pixel_type, fallback_only, imageio
            )
        else:
            raise FileNotFoundError(f'No such file or directory: "{input_path}"')

        affine = ItkIO.get_img_aff(img)
        metadata = MetaData(affine=affine, coord_sys=ItkIO.coord_sys)
        if (desired_axcodes is None) or (desired_axcodes == metadata.ornt):
            image_np = ItkIO.itk_img_to_array(img)
        else:
            orig_ornt = metadata.ornt
            img, _ = ItkIO.reorient(img, desired_axcodes)
            image_np, affine = ItkIO.unpack_img(img)
            metadata = MetaData(
                affine=affine, orig_ornt=orig_ornt, coord_sys=ItkIO.coord_sys
            )
        if header:
            if imageio:
                metadict = imageio.GetMetaDataDictionary()
            else:
                metadict = img.GetMetaDataDictionary()
            metadata.header = {
                key: metadict[key]
                for key in metadict.GetKeys()
                if not key.startswith("ITK_")
            }

        # TODO: consider unifying with PdcmIO.move_channels_axis
        n_components = img.GetNumberOfComponentsPerPixel()
        if (n_components > 1) and (components_axis is not None):
            # assert image_np.shape[ItkIO.DEFAULT_COMPONENTS_AXIS] == n_components
            image_np = np.moveaxis(
                image_np, ItkIO.DEFAULT_COMPONENTS_AXIS, components_axis
            )

        return image_np, metadata

    @staticmethod
    def save_img(
        filename,
        image_np,
        metadata,
        use_original_ornt=True,
        components_axis=None,
        allow_dcm_reorient=False,
        compression=False,
    ):
        """
        Save an image file with itk
        :param filename: the filename to save, str or os.PathLike
        :param image_np: the image's numpy array
        :param metadata: the corresponding metadata
        :param use_original_ornt: whether to save in the original orientation or not
        :param components_axis: if not None - the image has more than 1 component (e.g. RGB) and the components are in
        components_axis
        :param allow_dcm_reorient: whether to allow automatic reorientation to a right handed orientation or not
        :param compression: use compression or not
        """
        is_dcm = is_dicom(filename, check_exist=False)
        if is_dcm:
            image_np = ItkIO.prepare_dcm_array(
                image_np, is_vector=components_axis is not None
            )
        image = ItkIO.prepare_image(
            image_np,
            metadata,
            use_original_ornt,
            components_axis=components_axis,
            is_dcm=is_dcm,
            allow_dcm_reorient=allow_dcm_reorient,
        )
        ItkIO.save_img_file(image, str(filename), compression=compression)

    @staticmethod
    def prepare_image(
        image_np,
        metadata,
        use_original_ornt,
        components_axis=None,
        is_dcm=False,
        allow_dcm_reorient=False,
    ):
        """Prepare image for saving"""
        orig_coord_sys = metadata.coord_sys
        metadata.convert(ItkIO.coord_sys)
        desired_ornt = metadata.orig_ornt if use_original_ornt else None
        if is_dcm:
            # checking right-handed orientation before saving a dicom file/series
            desired_ornt = check_dcm_ornt(
                desired_ornt, metadata, allow_dcm_reorient=allow_dcm_reorient
            )
        image = ItkIO.pack2img(
            image_np, metadata.affine, components_axis=components_axis
        )
        if (desired_ornt is not None) and (desired_ornt != metadata.ornt):
            image, _ = ItkIO.reorient(image, desired_ornt)
        metadata.convert(orig_coord_sys)
        return image

    @staticmethod
    def prepare_dcm_array(image_np, is_vector=False):
        """Change image_np to correct data type for saving a single dicom file"""
        if is_vector:
            dcm_dtypes = [np.uint8]
        else:
            # for 3d image the supported data types are:
            dcm_dtypes = [np.uint8, np.uint16]
            # if the image is 2d it can be signed
            if np.squeeze(image_np).ndim == 2:
                dcm_dtypes = [np.int16] + dcm_dtypes

        if image_np.dtype in dcm_dtypes:
            return image_np

        for dtype in dcm_dtypes:
            arr = image_np.astype(dtype, copy=False)
            if np.array_equal(arr, image_np):
                return arr

        raise NotImplementedError(
            "Saving a single dicom file with ItkIO is currently supported only for \n"
            "1. 2d images - int16, uint16, uint8\n"
            "2. 3d images with integer nonnegative values - uint8, uint16\n"
            "3. 2d/3d RGB[A] images - uint8 (with channels_axis)\n"
            "For negative values, try to save a dicom directory or use PdcmIO.save_arr2dcm_file"
        )

    @staticmethod
    def read_img_file(filename, pixel_type=None, fallback_only=False, imageio=None):
        """Common pixel types: itk.SS (int16), itk.US (uint16), itk.UC (uint8)"""
        return itk.imread(filename, pixel_type, fallback_only, imageio)

    @staticmethod
    def read_img_file_long(filename, image_type=image_type):
        """Longer version of itk.imread that returns the itk image and io engine string"""
        reader = itk.ImageFileReader[image_type].New()
        reader.LoadPrivateTagsOn()
        reader.SetFileName(filename)
        reader.Update()
        image_io = str(reader.GetImageIO()).split(" ")[0]
        image = reader.GetOutput()
        return image, image_io

    @staticmethod
    def save_img_file(image, filename, compression=False):
        itk.imwrite(image, filename, compression)

    @staticmethod
    def save_img_file_long(image, filename, compression=False):
        image_type = type(image)
        writer = itk.ImageFileWriter[image_type].New()
        if compression:
            writer.UseCompressionOn()
        writer.UseInputMetaDataDictionaryOn()
        writer.SetFileName(filename)
        writer.SetInput(image)
        writer.Update()

    @staticmethod
    def itk_img_to_array(img_itk):
        """
        Swap the axes to the usual x, y, z convention in RAI orientation
        (originally z, y, x)
        """
        # the transpose here is equivalent to keep_axes=True
        img_array = itk.array_from_image(img_itk).T
        return img_array

    @staticmethod
    def array_to_itk_img(img_array, components_axis=None):
        """Set components_axis to not None for vector images, e.g. RGB"""
        is_vector = False
        if components_axis is not None:
            img_array = np.moveaxis(
                img_array, components_axis, ItkIO.DEFAULT_COMPONENTS_AXIS
            )
            is_vector = True
        # copy is crucial for the ordering
        img_itk = itk.image_from_array(img_array.T.copy(), is_vector=is_vector)
        return img_itk

    @staticmethod
    def unpack_img(img):
        image_np = ItkIO.itk_img_to_array(img)
        affine = ItkIO.get_img_aff(img)
        return image_np, affine

    @staticmethod
    def get_img_aff(img):
        direction = itk.array_from_vnl_matrix(
            img.GetDirection().GetVnlMatrix().as_matrix()
        )
        spacing = itk.array_from_vnl_vector(img.GetSpacing().GetVnlVector())
        origin = itk.array_from_vnl_vector(img.GetOrigin().GetVnlVector())
        return Affine(direction=direction, spacing=spacing, origin=origin)

    @staticmethod
    def pack2img(image_np, affine, components_axis=None):
        image = ItkIO.array_to_itk_img(image_np, components_axis)
        ItkIO.set_img_aff(image, affine)
        return image

    @staticmethod
    def set_img_aff(image, affine):
        if not isinstance(affine, Affine):
            affine = Affine(affine)

        dimension = image.GetImageDimension()
        direction_arr, spacing, origin = affine.direction, affine.spacing, affine.origin

        # setting metadata
        spacing_vec = itk.Vector[itk.D, dimension]()
        spacing_vec.SetVnlVector(itk.vnl_vector_from_array(spacing.astype("float")))
        image.SetSpacing(spacing_vec)

        image.SetOrigin(origin.astype("float"))

        direction_mat = itk.vnl_matrix_from_array(direction_arr.astype("float"))
        direction = itk.Matrix[itk.D, dimension, dimension](direction_mat)
        image.SetDirection(direction)

    @staticmethod
    def reorient(img, desired_orientation: Union[int, tuple, str, None]):
        if desired_orientation is None:
            return img, None

        image_type = type(img)
        orient = itk.OrientImageFilter[image_type, image_type].New()
        orient.UseImageDirectionOn()
        orient.SetInput(img)
        if isinstance(desired_orientation, (str, tuple)):
            desired_orientation = itk_orientation_code(desired_orientation)
        orient.SetDesiredCoordinateOrientation(desired_orientation)
        orient.Update()
        reoriented_itk_img = orient.GetOutput()
        original_orientation_code = orient.GetGivenCoordinateOrientation()
        return reoriented_itk_img, original_orientation_code

    @staticmethod
    def read_dir(
        dirname, pixel_type=None, fallback_only=False, series=None, imageio=None
    ):
        """
        Read a dicom directory. If there is more than one series in the directory an error is raised
        (unless the series argument is used properly).
        Shorter option for a single series (provided the slices order is known):
        >>> itk.imread([filename0, filename1, ...])
        """
        filenames = ItkIO.extract_series(dirname, series)
        return itk.imread(filenames, pixel_type, fallback_only, imageio)

    @staticmethod
    def extract_series(dirname, series=None):
        """Extract series filenames from the directory dirname"""
        names_generator = itk.GDCMSeriesFileNames.New()
        names_generator.SetDirectory(dirname)

        series_uids = names_generator.GetSeriesUIDs()
        series_uid = parse_series_uids(dirname, series_uids, series)

        filenames = names_generator.GetFileNames(series_uid)
        if len(filenames) == 1:
            filenames = filenames[0]  # there is a single image in the series

        return filenames

    @staticmethod
    def save_dcm_dir(
        dirname,
        image_np,
        metadata,
        use_original_ornt=True,
        components_axis=None,
        parents=False,
        exist_ok=False,
        allow_dcm_reorient=False,
        **kwargs,
    ):
        """
        Save a 3d numpy array image_np as a dicom series of 2d dicom slices in the directory dirname
        :param dirname: the directory to save in the files, str or pathlib.Path. If it exists - must be empty
        :param image_np: the image's numpy array
        :param metadata: the corresponding metadata
        :param use_original_ornt: whether to save in the original orientation or not
        :param components_axis: if not None - the image has more than 1 component (e.g. RGB) and the components are in
        components_axis
        :param parents: if True, creates also the parents of dirname
        :param exist_ok: if True, non-empty existing directory will not raise an error
        :param allow_dcm_reorient: whether to allow automatic reorientation to a right-handed orientation or not
        :param kwargs: optional kwargs passed to ItkIO.dcm_metadata: pattern, metadata_dict
        """
        image = ItkIO.prepare_image(
            image_np,
            metadata,
            use_original_ornt,
            components_axis=components_axis,
            is_dcm=True,
            allow_dcm_reorient=allow_dcm_reorient,
        )
        image_type = type(image)
        _, (pixel_type, _) = itk.template(image)
        image2d_type = itk.Image[pixel_type, 2]
        writer = itk.ImageSeriesWriter[image_type, image2d_type].New()
        make_dir(dirname, parents, exist_ok)
        # Generate necessary metadata and filenames per slice:
        mdict_list, filenames = ItkIO.dcm_series_metadata(image, dirname, **kwargs)
        metadict_vec = itk.vector[itk.MetaDataDictionary](mdict_list)
        writer.SetMetaDataDictionaryArray(metadict_vec)
        writer.SetFileNames(filenames)
        dicom_io = itk.GDCMImageIO.New()
        dicom_io.KeepOriginalUIDOn()
        writer.SetImageIO(dicom_io)
        writer.SetInput(image)
        writer.Update()

    @staticmethod
    def dcm_series_metadata(image, dirname, pattern="IM{}.dcm", metadata_dict=None):
        """
        Return dicom series metadata per slice and filenames
        :param image: the full itk image to be saved as dicom series
        :param dirname: the directory name
        :param pattern: str pattern for the filenames to save, including a placeholder ('{}') for the slice number
        :param metadata_dict: dictionary of metadata for adding tags or overriding the default values. For example,
        metadata_dict={'0008|0060': 'US'} will override the default 'CT' modality and set it to 'US' (ultrasound)
        :return: metadata dictionaries per slice, slice filenames
        """
        # The number of slices
        n = image.GetLargestPossibleRegion().GetSize().GetElement(2)

        # Shared properties for all the n slices:
        mdict = itk.MetaDataDictionary()

        # Series Instance UID
        mdict["0020|000e"] = generate_uid()
        # Study Instance UID
        mdict["0020|000d"] = generate_uid()

        date, time = datetime.now().strftime("%Y%m%d %H%M%S.%f").split()
        # Study Date
        mdict["0008|0020"] = date
        # Series Date
        mdict["0008|0021"] = date
        # Content Date
        mdict["0008|0023"] = date
        # Study Time
        mdict["0008|0030"] = time
        # Series Time
        mdict["0008|0031"] = time

        # Pixel Spacing (not necessary - automatically saved)
        spacing = image.GetSpacing()
        mdict["0028|0030"] = f"{spacing[0]}\\{spacing[1]}"
        # Spacing Between Slices
        mdict["0018|0088"] = str(spacing[2])
        # Image Orientation (Patient)
        orientation_str = "\\".join(
            [
                str(image.GetDirection().GetVnlMatrix().get(i, j))
                for j in range(2)
                for i in range(3)
            ]
        )
        mdict["0020|0037"] = orientation_str
        # Patient Position
        mdict["0018|5100"] = ""

        # Number of Frames
        mdict["0028|0008"] = "1"
        # Number of Slices
        mdict["0054|0081"] = str(n)
        # Modality
        mdict["0008|0060"] = "CT"

        if metadata_dict is not None:
            for key, val in metadata_dict.items():
                mdict[key] = val

        # Per slice properties:
        mdict_list = []
        filenames = []

        for i in range(n):
            # copy the shared properties dict:
            mdict_i = itk.MetaDataDictionary(mdict)
            # Instance Number
            mdict_i["0020|0013"] = str(i + 1)
            # Image Position (Patient)
            position = image.TransformIndexToPhysicalPoint([0, 0, i])
            position_str = "\\".join([str(position[i]) for i in range(3)])
            mdict_i["0020|0032"] = position_str

            mdict_list += [mdict_i]
            filenames += [str(Path(dirname) / pattern.format(i + 1))]

        return mdict_list, filenames
